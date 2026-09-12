"""Мастер по жизненной ситуации.

Вместо поиска по названию оператор проходит короткий опрос («у вас родился
ребёнок» -> «нужна регистрация» -> «нужны выплаты») и получает сразу пакет
связанных услуг: порядок обращения, общий чек-лист документов, сводку по
срокам и стоимости.

Услуги в сценариях не зашиты по id. Каждый вариант ответа задаёт поисковые
запросы, которые резолвятся через тот же гибридный поиск с фильтром по
жизненной ситуации. При обновлении выгрузки с mfc71.ru сценарии продолжают
работать без ручной правки.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..index_store import IndexStore, get_store
from ..search.hybrid import SearchFilters
from ..search.normalize import normalize_text

# Услуга попадает в пакет, если её релевантность запросу варианта не ниже
# этой доли от лучшего результата по тому же запросу.
RELATIVE_SCORE_FLOOR = 0.45
# Услуга из жизненной ситуации сценария получает приоритет над «просто похожей».
LS_BOOST = 1.6
# Услуга вне жизненной ситуации попадает в пакет, только если её название
# перекрывает запрос варианта хотя бы на эту долю ИНФОРМАТИВНОСТИ (сумма idf).
# Именно idf, а не число слов: «Государственная регистрация самоходных машин»
# делит с запросом про ККТ слова «регистрация» и «техника» — по количеству это
# половина запроса, по информативности — почти ничего.
TITLE_OVERLAP_FLOOR = 0.4
MAX_PACKAGE_SIZE = 14
# Пункт чек-листа считается «общим», если встречается минимум в стольких услугах.
COMMON_DOC_MIN = 2
RE_LIST_NOISE = re.compile(r"^(?:в случае|при обращении|для получения|если)\b", re.I)


class DocumentOntology:
    """Сводит разные формулировки одного документа к типовой категории.

    В регламентах паспорт описан десятком способов («документ, удостоверяющий
    личность», «оригинал паспорта либо иного документа...»). Без такой свёртки
    объединённый чек-лист пакета услуг превращается в список из 200+ пунктов,
    бесполезный в окне приёма.
    """

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.types = []
        for t in data["types"]:
            self.types.append({
                "id": t["id"], "label": t["label"], "critical": t.get("critical", False),
                "match": [re.compile(p, re.I) for p in t["match"]],
                "exclude": [re.compile(p, re.I) for p in t.get("exclude", [])],
            })

    def classify(self, text: str) -> dict | None:
        low = text.lower().replace("ё", "е")
        for t in self.types:
            if any(p.search(low) for p in t["match"]) and not any(
                p.search(low) for p in t["exclude"]
            ):
                return t
        return None


@dataclass
class ResolvedService:
    service_id: str
    score: float
    stage: int
    reasons: list[str] = field(default_factory=list)


class WizardEngine:
    def __init__(self, store: IndexStore | None = None, path: Path | None = None):
        self.store = store or get_store()
        from ..config import get_settings

        cfg_path = path or (get_settings().dict_dir / "life_situations.json")
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.scenarios: list[dict] = data["scenarios"]
        self.ontology = DocumentOntology(get_settings().dict_dir / "document_types.json")
        self._by_id = {s["id"]: s for s in self.scenarios}

    # ------------------------------------------------------------- сценарии
    def list_scenarios(self) -> list[dict]:
        out = []
        for s in self.scenarios:
            names = [
                self.store.classification("by_life_situation").get(i, {}).get("name")
                for i in s.get("lifeSituationIds", [])
            ]
            out.append({
                "id": s["id"], "title": s["title"], "subtitle": s.get("subtitle", ""),
                "emoji": s.get("emoji", ""), "steps": len(s["steps"]),
                "lifeSituations": [n for n in names if n],
            })
        return out

    def scenario(self, scenario_id: str) -> dict | None:
        s = self._by_id.get(scenario_id)
        if not s:
            return None
        return {
            "id": s["id"], "title": s["title"], "subtitle": s.get("subtitle", ""),
            "emoji": s.get("emoji", ""),
            "steps": [
                {
                    "id": st["id"], "question": st["question"],
                    "hint": st.get("hint", ""), "multi": st.get("multi", False),
                    "options": [{"id": o["id"], "label": o["label"]} for o in st["options"]],
                } for st in s["steps"]
            ],
        }

    # -------------------------------------------------------------- подбор
    def _idf_mass(self, lemmas: set[str]) -> float:
        """Суммарная информативность набора лемм по корпусу базы знаний.

        Лемма, которой нет в корпусе вообще («контрольно-кассовый»), считается
        максимально информативной. Иначе запрос про ККТ, ни одного слова
        которого нет в базе, «схлопнулся» бы до общих слов «регистрация» и
        «техника» — и любая регистрация техники прошла бы как точное совпадение.
        """
        bm25 = self.store.searcher.bm25
        fallback = self.store.searcher._idf_max
        total = 0.0
        for lm in lemmas:
            col = bm25.vocabulary.get(lm)
            total += float(bm25.idf[col]) if col is not None else fallback
        return total

    def _resolve_queries(
        self, queries: list[str], limit: int, ls_ids: list[str],
        require: str | None = None, exclude: str | None = None,
    ) -> list[tuple[str, float]]:
        """Подбирает услуги под вариант ответа.

        Жизненная ситуация используется как БУСТ, а не как жёсткий фильтр:
        только у 363 услуг из 732 в выгрузке вообще проставлены
        lifeSituationIds (см. docs/DATA_ANALYSIS.md), поэтому фильтрация по
        ним теряет половину базы. Зато услуга «не из ситуации» попадает
        в пакет, только если её название действительно отвечает запросу.
        """
        if not queries or limit <= 0:
            return []
        require_re = re.compile(require, re.I) if require else None
        exclude_re = re.compile(exclude, re.I) if exclude else None
        ls_set = set(ls_ids)
        merged: dict[str, float] = {}
        searcher = self.store.searcher

        for q in queries:
            q_lemmas = set(normalize_text(q))
            q_mass = self._idf_mass(q_lemmas) or 1.0
            hits, _ = searcher.search_services(q, limit=limit * 6)
            scored: list[tuple[float, str]] = []
            for h in hits:
                svc = self.store.service(h.service_id) or {}
                title = svc.get("title", "")
                if require_re and not require_re.search(title):
                    continue
                if exclude_re and exclude_re.search(title):
                    continue

                in_situation = bool(ls_set & set(svc.get("life_situation_ids") or []))
                if not in_situation:
                    # услуга вне жизненной ситуации — требуем совпадения по названию
                    title_lemmas = set(normalize_text(title))
                    overlap = self._idf_mass(q_lemmas & title_lemmas) / q_mass
                    if overlap < TITLE_OVERLAP_FLOOR:
                        continue
                scored.append((h.score * (LS_BOOST if in_situation else 1.0), h.service_id))

            if not scored:
                continue
            scored.sort(reverse=True)
            top = scored[0][0]
            for score, sid in scored[:limit]:
                if score < top * RELATIVE_SCORE_FLOOR:
                    break
                merged[sid] = max(merged.get(sid, 0.0), score)
        return sorted(merged.items(), key=lambda kv: -kv[1])[:limit]

    def build_package(
        self, scenario_id: str, answers: dict[str, list[str]],
    ) -> dict[str, Any] | None:
        scenario = self._by_id.get(scenario_id)
        if not scenario:
            return None
        ls_ids = scenario.get("lifeSituationIds", [])

        resolved: dict[str, ResolvedService] = {}

        def add(items: list[tuple[str, float]], stage: int, reason: str) -> None:
            for sid, score in items:
                cur = resolved.get(sid)
                if cur is None:
                    resolved[sid] = ResolvedService(sid, score, stage, [reason])
                else:
                    cur.score = max(cur.score, score)
                    cur.stage = min(cur.stage, stage)
                    if reason not in cur.reasons:
                        cur.reasons.append(reason)

        always = scenario.get("always") or {}
        add(self._resolve_queries(always.get("queries", []), always.get("limit", 0), ls_ids),
            0, "Базовая услуга ситуации")

        chosen_labels: list[dict[str, str]] = []
        for stage, step in enumerate(scenario["steps"], start=1):
            selected = answers.get(step["id"]) or []
            for opt in step["options"]:
                if opt["id"] not in selected:
                    continue
                chosen_labels.append({"step": step["question"], "answer": opt["label"]})
                add(self._resolve_queries(
                    opt.get("queries", []), opt.get("limit", 0), ls_ids,
                    require=opt.get("requireTitle"), exclude=opt.get("excludeTitle"),
                ), stage, opt["label"])

        # Ничего не выбрано — покажем ядро жизненной ситуации
        if not resolved and ls_ids:
            for sid, svc in self.store.services.items():
                if set(ls_ids) & set(svc["life_situation_ids"]):
                    resolved[sid] = ResolvedService(sid, svc["completeness"], 1,
                                                    ["Услуга этой жизненной ситуации"])

        ordered = self._collapse_variants(
            sorted(resolved.values(), key=lambda r: (r.stage, -r.score))
        )[:MAX_PACKAGE_SIZE]
        services = [self._service_card(r) for r in ordered]
        checklist = self._merge_checklist(ordered)

        departments = sorted({s["department"] for s in services if s["department"]})
        return {
            "scenarioId": scenario_id,
            "title": scenario["title"],
            "emoji": scenario.get("emoji", ""),
            "answers": chosen_labels,
            "services": services,
            "checklist": checklist,
            "summary": {
                "servicesCount": len(services),
                "departments": departments,
                "departmentsCount": len(departments),
                "freeCount": sum(1 for s in services if s["isFree"]),
                "commonDocs": len(checklist["common"]),
                "visitsHint": self._visits_hint(services),
            },
        }

    def _collapse_variants(self, items: list[ResolvedService]) -> list[ResolvedService]:
        """Оставляет один экземпляр муниципальной услуги вместо 26 одинаковых."""
        out: list[ResolvedService] = []
        seen: set[str] = set()
        for r in items:
            svc = self.store.service(r.service_id) or {}
            group = svc.get("variant_group")
            if group:
                if group in seen:
                    continue
                seen.add(group)
            out.append(r)
        return out

    # ----------------------------------------------------------- карточки
    def _service_card(self, r: ResolvedService) -> dict[str, Any]:
        svc = self.store.service(r.service_id) or {}
        term = self._first_line(svc, "term")
        payment = self._first_line(svc, "payment")
        is_free = bool(payment) and any(
            w in payment.lower() for w in ("бесплатн", "не взимается", "без взимания",
                                           "госпошлина не", "0 руб")
        )
        return {
            "id": r.service_id,
            "title": svc.get("title", r.service_id),
            "shortTitle": svc.get("short_title", ""),
            "department": svc.get("department"),
            "stage": r.stage,
            "reasons": r.reasons,
            "term": term,
            "payment": payment,
            "isFree": is_free,
            "completeness": svc.get("completeness", 0.0),
            "variantLabel": svc.get("variant_label") or None,
            "variantCount": len(
                self.store.variant_groups.get(svc.get("variant_group") or "", [])
            ),
            "missingSections": svc.get("missing_sections", []),
            "score": round(r.score, 4),
        }

    @staticmethod
    def _first_line(svc: dict, section: str, limit: int = 180) -> str:
        sec = (svc.get("sections") or {}).get(section)
        if not sec:
            return ""
        text = (sec.get("text") or "").strip()
        if not text:
            return ""
        line = text.split("\n", 1)[0].strip()
        return line if len(line) <= limit else line[:limit].rsplit(" ", 1)[0] + "…"

    # ------------------------------------------------------------ чек-лист
    def _merge_checklist(self, ordered: list[ResolvedService]) -> dict[str, Any]:
        """Сводит перечни документов услуг в единый чек-лист приёма.

        Два уровня свёртки:
          1. типовые документы — по онтологии (паспорт, СНИЛС, заявление…);
          2. остальные пункты — по совпадению множества лемм.
        Оператор получает ответ на главный вопрос пакета: «что попросить
        у заявителя один раз на все услуги».
        """
        typed: dict[str, dict[str, Any]] = {}
        other: dict[frozenset[str], dict[str, Any]] = {}

        for r in ordered:
            svc = self.store.service(r.service_id) or {}
            sec = (svc.get("sections") or {}).get("documents")
            if not sec:
                continue
            seen_types: set[str] = set()
            for block in sec.get("blocks", []):
                text = (block.get("text") or "").strip(" .;")
                if not (12 <= len(text) <= 300) or block.get("kind") == "heading":
                    continue
                if RE_LIST_NOISE.match(text):
                    continue

                kind = self.ontology.classify(text)
                if kind:
                    if kind["id"] in seen_types:
                        continue
                    seen_types.add(kind["id"])
                    item = typed.setdefault(kind["id"], {
                        "id": kind["id"], "text": kind["label"],
                        "critical": kind["critical"], "services": [],
                        "count": 0, "wordings": [],
                    })
                    if r.service_id not in item["services"]:
                        item["services"].append(r.service_id)
                        item["count"] += 1
                    if len(item["wordings"]) < 4 and text not in item["wordings"]:
                        item["wordings"].append(text)
                    continue

                lemmas = frozenset(normalize_text(text))
                if len(lemmas) < 3:
                    continue
                item = other.setdefault(lemmas, {
                    "id": None, "text": text, "critical": False,
                    "services": [], "count": 0, "wordings": [],
                })
                if len(text) < len(item["text"]):
                    item["text"] = text
                if r.service_id not in item["services"]:
                    item["services"].append(r.service_id)
                    item["count"] += 1

        common = sorted(typed.values(), key=lambda i: (-i["critical"], -i["count"]))
        specific = sorted(other.values(), key=lambda i: (-i["count"], len(i["text"])))
        return {
            "common": common,
            "specific": specific[:30],
            "totalUnique": len(typed) + len(other),
        }

    @staticmethod
    def _visits_hint(services: list[dict]) -> str:
        deps = len({s["department"] for s in services if s["department"]})
        if not services:
            return "Услуги не подобраны — уточните ответы."
        if deps <= 1:
            return "Весь пакет можно подать за один визит в одно окно."
        return (f"Услуги относятся к {deps} ведомствам, но принимаются в МФЦ "
                f"по принципу «одного окна» — визит может быть один.")


_engine: WizardEngine | None = None


def get_wizard() -> WizardEngine:
    global _engine
    if _engine is None:
        _engine = WizardEngine()
    return _engine
