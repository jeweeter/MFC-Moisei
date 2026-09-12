"""Сборка поискового индекса из data/raw/*.json.

Запуск:  python -m app.ingest.build_index
Результат: data/index/index.pkl — самодостаточный артефакт, который сервер
поднимает за доли секунды. Пересборка запускается автоматически, если
изменились исходные файлы, словари или версия кода индексатора.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings  # noqa: E402
from app.ingest.chunker import build_chunks, chunk_search_text  # noqa: E402
from app.ingest.html_clean import clean_html  # noqa: E402
from app.ingest.schema import (  # noqa: E402
    RECIPIENT_LABELS,
    SECTIONS,
    UNUSED_FIELDS,
)
from app.search.normalize import normalize_text  # noqa: E402

INDEXER_VERSION = "6"

# Хвостовые уточнения в скобках: «(Тула)», «(Алексин)», «(Комплексная)».
RE_TRAILING_PAREN = re.compile(r"\s*\(([^()]{1,60})\)\s*$")
# Муниципальные дубли группируются, начиная с такого размера группы.
VARIANT_MIN_GROUP = 3

RE_WS = re.compile(r"\s+")
# Хвосты официальных наименований, которые не нужны оператору в списке.
RE_TITLE_TAIL = re.compile(
    r"\s*(?:,\s*(?:в том числе|за исключением|а также|в части)\b"
    r"|\s+в соответствии с\b"
    r"|\s+в рамках\b)",
    re.IGNORECASE,
)


# Канцелярские зачины, одинаковые у сотен услуг — в списке они бесполезны.
RE_BOILERPLATE = re.compile(
    r"^(?:предоставление государственной услуги|предоставление муниципальной услуги"
    r"|оказание государственной услуги|государственная услуга|муниципальная услуга"
    r"|услуга|осуществление|организация)\s+[«\"]?",
    re.IGNORECASE,
)


def _cut_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    out: list[str] = []
    total = 0
    for w in text.split(" "):
        if total + len(w) + 1 > limit:
            break
        out.append(w)
        total += len(w) + 1
    return " ".join(out).rstrip(" ,;:-—") or text[:limit]


def short_title(title: str, limit: int = 120) -> str:
    """Короткое имя услуги для списков и чата.

    В исходных данных нет «человеческого» названия: средняя длина
    serviceTitleText — 166 символов, максимум — 1000 (см. docs/DATA_ANALYSIS.md,
    предложение №1). Простое обрезание слева непригодно: у пары «паспорт РФ» и
    «загранпаспорт» официальные названия различаются ТОЛЬКО хвостом
    («…на территории РФ» / «…за пределами территории РФ»). Поэтому строим
    форму «голова … различающий хвост».
    """
    t = RE_WS.sub(" ", (title or "").strip()).strip("«»\" ")
    t = RE_BOILERPLATE.sub("", t).strip()
    if len(t) <= limit:
        return t

    # 1) отрезаем типовые уточняющие хвосты, если голова осталась осмысленной
    cut = RE_TITLE_TAIL.search(t)
    if cut and cut.start() > 45:
        candidate = t[: cut.start()].strip(" ,;:")
        if len(candidate) <= limit:
            return candidate
        t = candidate

    # 2) голова + различающий хвост
    tail_sep = max(t.rfind(", "), t.rfind(" за "), t.rfind(" на "), t.rfind(" ("))
    if tail_sep > limit // 2:
        tail = t[tail_sep:].strip(" ,")
        if 8 <= len(tail) <= limit // 2:
            head = _cut_words(t[:tail_sep], limit - len(tail) - 2)
            return f"{head}… {tail}".replace("…  ", "… ")
    return _cut_words(t, limit) + "…"


def variant_base(title: str) -> tuple[str, list[str]]:
    """Отделяет «тело» названия от хвостовых уточнений в скобках.

    В выгрузке одна и та же муниципальная услуга продублирована по каждому
    муниципальному образованию: «Выдача разрешений на ввод объектов в
    эксплуатацию … (Алексин)», «… (Белевский)», «… (Донской)» — 22 записи
    на одну услугу. Оператору нужен один результат поиска с выбором
    муниципалитета, а не 22 одинаковые строки.
    """
    t = RE_WS.sub(" ", (title or "").strip())
    labels: list[str] = []
    while True:
        m = RE_TRAILING_PAREN.search(t)
        if not m:
            break
        labels.insert(0, m.group(1).strip())
        t = t[: m.start()].strip()
    return t.lower().rstrip(" .,;"), labels


DEPARTMENT_SHORTCUTS = (
    ("Администрация муниципального образования", "АМО"),
    ("Управление Министерства внутренних дел России по", "УМВД по"),
    ("Управление Министерства юстиции Российской Федерации по", "Минюст по"),
    ("Управление Федеральной налоговой службы России по", "УФНС по"),
    ("Управление Федеральной службы судебных приставов по", "УФССП по"),
    ("Отделение Фонда пенсионного и социального страхования по", "СФР по"),
    ("Территориальный отдел опеки министерства труда и социальной защиты", "Опека Минтруда"),
    ("Государственное учреждение Тульской обл.", "ГУ ТО"),
    ("Министерство труда и социальной защиты", "Минтруд"),
    ("Министерство природных ресурсов и экологии", "Минприроды"),
    ("Акционерное общество (АО)", "АО"),
    ("Тульской области", "Тульской обл."),
)


def short_department(name: str, limit: int = 42) -> str:
    """Компактное имя ведомства для фильтров.

    Полные наименования различаются только хвостом («Администрация
    муниципального образования Арсеньевский район» / «…Белевский район»),
    поэтому обычное обрезание слева делает список фильтров нечитаемым.
    """
    t = RE_WS.sub(" ", (name or "").strip())
    for full, short in DEPARTMENT_SHORTCUTS:
        t = t.replace(full, short)
    t = RE_WS.sub(" ", t).strip()
    if len(t) <= limit:
        return t
    # оставляем различающий хвост
    return "…" + t[-(limit - 1):].lstrip(" ,")


@dataclass
class ServiceRecord:
    id: str
    title: str
    short_title: str
    department_id: str | None
    department: str | None
    recipients: list[str]
    recipient_ids: list[str]
    life_situation_ids: list[str]
    life_situations: list[str]
    branch_ids: list[str]
    branch_count: int
    sections: dict[str, dict[str, Any]]      # code -> {label, text, blocks, links}
    raw_sections: dict[str, str]             # code -> исходный HTML (для «оригинала»)
    completeness: float
    missing_sections: list[str]
    variant_key: str = ""
    variant_label: str = ""
    variant_group: str | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hash_sources(paths: list[Path]) -> str:
    h = hashlib.sha256()
    h.update(INDEXER_VERSION.encode())
    for p in sorted(paths):
        h.update(p.name.encode())
        if p.exists():
            st = p.stat()
            h.update(str(st.st_size).encode())
            h.update(str(int(st.st_mtime)).encode())
    return h.hexdigest()[:16]


def load_classification(path: Path) -> dict[str, dict[str, dict]]:
    """-> {'by_department': {id: category}, ...}"""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, dict]] = {}
    for block in data:
        bid = block.get("id")
        out[bid] = {c["id"]: c for c in block.get("categories", []) if c.get("id")}
    return out


def build_services(
    db: list[dict], classification: dict[str, dict[str, dict]]
) -> tuple[list[ServiceRecord], dict[str, Any]]:
    departments = classification.get("by_department", {})
    branches = classification.get("by_branch", {})
    situations = classification.get("by_life_situation", {})

    stats: dict[str, Any] = {
        "services": len(db),
        "missing_department": 0,
        "unknown_department_ids": set(),
        "unknown_branch_ids": set(),
        "empty_sections": {s.code: 0 for s in SECTIONS},
        "html_sections": {s.code: 0 for s in SECTIONS},
        "raw_bytes": 0,
        "clean_bytes": 0,
        "images_dropped": 0,
        "no_life_situation": 0,
        "no_branches": 0,
    }

    records: list[ServiceRecord] = []
    for row in db:
        sid = str(row.get("id"))
        title = RE_WS.sub(" ", (row.get("serviceTitleText") or "").strip())

        dep_id = row.get("departmentId")
        dep = departments.get(dep_id, {}).get("name") if dep_id else None
        if not dep_id:
            stats["missing_department"] += 1
        elif dep is None:
            stats["unknown_department_ids"].add(dep_id)

        ls_ids = [i for i in (row.get("lifeSituationIds") or []) if i]
        ls_names = [situations[i]["name"] for i in ls_ids if i in situations]
        if not ls_ids:
            stats["no_life_situation"] += 1

        br_ids = [i for i in (row.get("mfcIds") or []) if i]
        for b in br_ids:
            if b not in branches:
                stats["unknown_branch_ids"].add(b)
        if not br_ids:
            stats["no_branches"] += 1

        rec_ids = [i for i in (row.get("recipientIds") or []) if i]
        recipients = [RECIPIENT_LABELS.get(i, i) for i in rec_ids]

        sections: dict[str, dict[str, Any]] = {}
        raw_sections: dict[str, str] = {}
        missing: list[str] = []
        for spec in SECTIONS:
            raw = row.get(spec.key)
            raw_str = raw if isinstance(raw, str) else ""
            stats["raw_bytes"] += len(raw_str)
            if spec.code == "title":
                cleaned_text, blocks, links = title, [], []
            else:
                if "<" in raw_str and ">" in raw_str:
                    stats["html_sections"][spec.code] += 1
                res = clean_html(raw_str)
                stats["images_dropped"] += res.images_dropped
                cleaned_text, blocks, links = res.text, res.blocks, res.links
            stats["clean_bytes"] += len(cleaned_text)

            if not cleaned_text.strip():
                stats["empty_sections"][spec.code] += 1
                if spec.code != "title":
                    missing.append(spec.code)
                continue
            raw_sections[spec.code] = raw_str
            sections[spec.code] = {
                "label": spec.label,
                "text": cleaned_text,
                "blocks": [b.to_dict() for b in blocks],
                "links": links,
            }

        informative = [s.code for s in SECTIONS if s.code != "title"]
        filled = sum(1 for c in informative if c in sections)
        completeness = round(filled / len(informative), 3)

        flags: list[str] = []
        if completeness < 0.5:
            flags.append("low_completeness")
        if not dep:
            flags.append("no_department")
        if not br_ids:
            flags.append("no_branches")
        if len(title) > 300:
            flags.append("long_title")

        vkey, vlabels = variant_base(title)
        records.append(ServiceRecord(
            id=sid, title=title, short_title=short_title(title),
            variant_key=vkey, variant_label=", ".join(vlabels),
            department_id=dep_id, department=dep,
            recipients=recipients, recipient_ids=rec_ids,
            life_situation_ids=ls_ids, life_situations=ls_names,
            branch_ids=br_ids, branch_count=len(br_ids),
            sections=sections, raw_sections=raw_sections,
            completeness=completeness, missing_sections=missing, flags=flags,
        ))

    # --- группировка муниципальных дублей ---
    groups: dict[str, list[ServiceRecord]] = {}
    for rec in records:
        if rec.variant_key and rec.variant_label:
            groups.setdefault(rec.variant_key, []).append(rec)
    variant_groups: dict[str, list[str]] = {}
    for key, items in groups.items():
        if len(items) < VARIANT_MIN_GROUP:
            continue
        variant_groups[key] = [r.id for r in items]
        for r in items:
            r.variant_group = key
    stats["variant_groups"] = len(variant_groups)
    stats["variant_services"] = sum(len(v) for v in variant_groups.values())
    stats["largest_variant_groups"] = sorted(
        ({"title": k[:120], "count": len(v)} for k, v in variant_groups.items()),
        key=lambda g: -g["count"],
    )[:12]

    stats["unknown_department_ids"] = sorted(stats["unknown_department_ids"])
    stats["unknown_branch_ids"] = sorted(stats["unknown_branch_ids"])
    return records, stats, variant_groups


def build(verbose: bool = True) -> dict[str, Any]:
    s = get_settings()
    t0 = time.time()

    db = json.loads(s.knowledge_file.read_text(encoding="utf-8"))
    classification = load_classification(s.classification_file)
    if verbose:
        print(f"[1/5] загружено услуг: {len(db)}")

    services, quality, variant_groups = build_services(db, classification)
    if verbose:
        print(f"[2/5] очищено полей, мусора удалено: "
              f"{100 - quality['clean_bytes'] / max(1, quality['raw_bytes']) * 100:.1f}%")

    # --- чанки ---
    chunks = []
    for rec in services:
        chunks.extend(build_chunks(rec.id, rec.title, rec.sections))
    if verbose:
        print(f"[3/5] фрагментов для RAG: {len(chunks)}")

    by_id = {r.id: r for r in services}
    docs_tokens: list[list[str]] = []
    docs_chars: list[str] = []
    for ch in chunks:
        rec = by_id[ch.service_id]
        extra = " ".join(rec.recipients + rec.life_situations + ([rec.department] if rec.department else []))
        text = chunk_search_text(ch, rec.title, extra)
        toks = normalize_text(text)
        ch.tokens = toks
        docs_tokens.append(toks)
        docs_chars.append(text.lower().replace("ё", "е")[:3000])

    # --- BM25 (лексический слой) ---
    count_vec = CountVectorizer(analyzer=lambda x: x, lowercase=False, min_df=1, dtype=np.int32)
    tf = count_vec.fit_transform(docs_tokens).tocsc()
    if verbose:
        print(f"[4/5] словарь лемм: {len(count_vec.vocabulary_)}")

    # --- Символьные n-граммы (устойчивость к опечаткам и словоформам) ---
    char_vec = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 4), min_df=3,
        max_features=200_000, sublinear_tf=True, dtype=np.float32,
    )
    char_matrix = char_vec.fit_transform(docs_chars)

    # --- индекс уровня услуги (для быстрого фильтра и «похожих») ---
    service_ids = [r.id for r in services]
    service_titles_tokens = [normalize_text(f"{r.title} {' '.join(r.life_situations)}") for r in services]
    title_vec = CountVectorizer(analyzer=lambda x: x, lowercase=False, min_df=1, dtype=np.int32)
    title_tf = title_vec.fit_transform(service_titles_tokens).tocsc()

    payload = {
        "version": INDEXER_VERSION,
        "built_at": time.time(),
        "source_hash": _hash_sources([s.knowledge_file, s.classification_file,
                                      s.dict_dir / "synonyms.json"]),
        "services": {r.id: r.to_dict() for r in services},
        "service_order": service_ids,
        "chunks": [c.to_dict() for c in chunks],
        "chunk_service": [c.service_id for c in chunks],
        "chunk_weight": np.array([c.weight for c in chunks], dtype=np.float32),
        "chunk_section": [c.section for c in chunks],
        "bm25": {"vocabulary": count_vec.vocabulary_, "tf": tf},
        "char": {"vectorizer": char_vec, "matrix": char_matrix},
        "title_bm25": {"vocabulary": title_vec.vocabulary_, "tf": title_tf},
        "classification": {
            k: {cid: {kk: vv for kk, vv in c.items() if kk != "ids"}
                for cid, c in v.items()}
            for k, v in classification.items()
        },
        "variant_groups": variant_groups,
        "quality": quality,
        "build_seconds": 0.0,
    }
    payload["build_seconds"] = round(time.time() - t0, 2)

    s.index_dir.mkdir(parents=True, exist_ok=True)
    tmp = s.index_dir / "index.pkl.tmp"
    with tmp.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(s.index_dir / "index.pkl")
    if verbose:
        size = (s.index_dir / "index.pkl").stat().st_size / 1e6
        print(f"[5/5] индекс сохранён: {size:.1f} МБ за {payload['build_seconds']} с")
    return payload


def index_is_fresh() -> bool:
    s = get_settings()
    path = s.index_dir / "index.pkl"
    if not path.exists():
        return False
    try:
        with path.open("rb") as f:
            head = pickle.load(f)
    except Exception:
        return False
    if head.get("version") != INDEXER_VERSION:
        return False
    return head.get("source_hash") == _hash_sources(
        [s.knowledge_file, s.classification_file, s.dict_dir / "synonyms.json"]
    )


if __name__ == "__main__":
    build()
