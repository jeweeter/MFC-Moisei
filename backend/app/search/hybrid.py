"""Гибридный поиск: BM25 по леммам + косинус по символьным n-граммам.

Почему гибрид, а не «просто эмбеддинги»:
  * BM25 по леммам точно ловит термины из регламента («госпошлина», «ЕГРН»);
  * символьные n-граммы вытягивают опечатки и словоформы, которых нет в словаре
    («заграничнй», «маткапитл», «прописатся»);
  * ранги объединяются через RRF — не нужно калибровать шкалы между собой;
  * всё считается локально, без внешнего сервиса эмбеддингов: развернуть можно
    в закрытом контуре МФЦ, где интернет ограничен.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
from rapidfuzz import fuzz as rf_fuzz
from rapidfuzz import process as rf_process

from .bm25 import BM25Index
from .normalize import (
    INTENT_WORDS,
    QueryAnalysis,
    SynonymIndex,
    fix_layout,
    is_known_word,
    looks_like_wrong_layout,
    normalize_text,
    tokenize,
)

RRF_K = 60
INTENT_WEIGHT = 0.45
# Вклад канала названий в итоговый балл услуги.
TITLE_CHANNEL_WEIGHT = 0.45
EXPANSION_WEIGHT = 0.55
FUZZY_MIN_LEN = 5
FUZZY_CUTOFF = 82
FUZZY_MAX_LEN_DELTA = 3
MAX_EXPANSION_TOKENS = 14


@dataclass
class ChunkHit:
    chunk_index: int
    chunk_id: str
    service_id: str
    section: str
    section_label: str
    text: str
    score: float
    lexical: float = 0.0
    fuzzy: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk_id,
            "serviceId": self.service_id,
            "section": self.section,
            "sectionLabel": self.section_label,
            "text": self.text,
            "score": round(self.score, 4),
        }


@dataclass
class ServiceHit:
    service_id: str
    score: float
    best_section: str
    best_chunk: str
    snippet: str
    matched_sections: list[str] = field(default_factory=list)
    chunk_hits: list[ChunkHit] = field(default_factory=list)


@dataclass
class SearchFilters:
    departments: list[str] = field(default_factory=list)
    life_situations: list[str] = field(default_factory=list)
    recipients: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    service_ids: list[str] | None = None

    def is_empty(self) -> bool:
        return not (self.departments or self.life_situations
                    or self.recipients or self.branches or self.service_ids)


class HybridSearcher:
    def __init__(self, index: dict[str, Any], synonyms: SynonymIndex):
        self.index = index
        self.synonyms = synonyms
        self.services: dict[str, dict] = index["services"]
        self.chunks: list[dict] = index["chunks"]
        self.chunk_service: list[str] = index["chunk_service"]
        self.chunk_weight: np.ndarray = index["chunk_weight"]
        self.bm25 = BM25Index(index["bm25"]["vocabulary"], index["bm25"]["tf"])
        # Отдельный индекс по названиям услуг: когда оператор называет услугу
        # почти дословно, название — самый чистый сигнал, и его нельзя
        # «размывать» о совпадения в перечнях документов у соседних услуг.
        self.title_bm25 = BM25Index(
            index["title_bm25"]["vocabulary"], index["title_bm25"]["tf"]
        )
        self.service_order: list[str] = index["service_order"]
        self.service_pos: dict[str, int] = {
            sid: i for i, sid in enumerate(self.service_order)
        }
        self.char_vec = index["char"]["vectorizer"]
        self.char_matrix = index["char"]["matrix"]
        self.vocab_terms: list[str] = list(self.bm25.vocabulary.keys())
        idf = self.bm25.idf
        self._idf_max = float(idf.max()) if idf.size else 1.0
        # Порог «слишком общего» слова. Квантиль здесь не годится: словарь
        # сильно скошен (большинство лемм встречается в 1-3 фрагментах), и любой
        # квантиль выше 0.2 срезал бы осмысленные термины. Фиксированный порог
        # 0.9 отсекает только слова, присутствующие более чем в ~55% фрагментов.
        self._idf_floor = 0.9
        # обратный индекс: услуга -> позиции её чанков
        self.by_service: dict[str, list[int]] = {}
        for i, sid in enumerate(self.chunk_service):
            self.by_service.setdefault(sid, []).append(i)

    # ------------------------------------------------------------------ query
    def _maybe_fix_layout(self, raw: str) -> tuple[str, bool]:
        """Латиница, набранная вместо кириллицы.

        Общая эвристика (по словарю русского языка) ловит «ghjgbcrf» ->
        «прописка», но не ловит жаргон вроде «pfuhfy» -> «загран»: такого
        слова в словаре нет. Поэтому дополнительно проверяем, попадает ли
        перекодированный текст в лексикон самой базы знаний или в словарь
        сокращений.
        """
        if looks_like_wrong_layout(raw):
            return fix_layout(raw), True

        letters = [c for c in raw.lower() if c.isalpha()]
        if len(letters) < 4 or any("а" <= c <= "я" for c in letters):
            return raw, False

        converted = fix_layout(raw)
        lemmas = normalize_text(converted, drop_stopwords=False)
        if not lemmas:
            return raw, False
        if self.synonyms.match(lemmas):
            return converted, True
        if any(lm in self.bm25.vocabulary and len(lm) >= 4 for lm in lemmas):
            return converted, True
        return raw, False

    def analyze(self, query: str) -> QueryAnalysis:
        raw = (query or "").strip()
        text, layout_fixed = self._maybe_fix_layout(raw)

        tokens = normalize_text(text)
        analysis = QueryAnalysis(
            raw=raw, normalized=text, tokens=tokens, layout_fixed=layout_fixed
        )

        # 1) сокращения и разговорные формулировки
        expansion: list[str] = []
        for entry in self.synonyms.match(normalize_text(text, drop_stopwords=False)):
            if entry.hint:
                analysis.hints.append(entry.hint)
            for phrase in entry.expand_to:
                expansion.extend(normalize_text(phrase))

        # 2) опечатки: токенов нет в словаре корпуса -> ближайшая лемма.
        # Скорер именно ratio (не WRatio): частичное совпадение сводит
        # «маткапитал» к «ка», а «несудимость» к «суд».
        for tok in tokens:
            if tok in self.bm25.vocabulary or len(tok) < FUZZY_MIN_LEN:
                continue
            # Обычное русское слово, которого просто нет в базе знаний
            # («делать», «желать»), — это не опечатка, исправлять нечего.
            if tok in INTENT_WORDS or is_known_word(tok):
                continue
            candidates = [
                v for v in self.vocab_terms
                if abs(len(v) - len(tok)) <= FUZZY_MAX_LEN_DELTA
            ]
            match = rf_process.extractOne(
                tok, candidates, scorer=rf_fuzz.ratio, score_cutoff=FUZZY_CUTOFF
            )
            if match:
                analysis.corrections.append({"from": tok, "to": match[0]})
                expansion.append(match[0])

        seen = set(tokens)
        unique = [t for t in expansion if not (t in seen or seen.add(t))]
        # Расширения ранжируем по редкости: общие слова из расшифровок
        # («предоставление», «лицо», «государственный») только зашумляют выдачу.
        analysis.expansion_tokens = self._rank_expansions(unique)
        return analysis

    def _rank_expansions(self, tokens: list[str]) -> list[str]:
        scored: list[tuple[float, str]] = []
        for t in tokens:
            col = self.bm25.vocabulary.get(t)
            idf = float(self.bm25.idf[col]) if col is not None else 0.0
            if col is not None and idf < self._idf_floor:
                continue
            scored.append((idf, t))
        scored.sort(reverse=True)
        return [t for _, t in scored[:MAX_EXPANSION_TOKENS]]

    def expansion_weight(self, token: str) -> float:
        col = self.bm25.vocabulary.get(token)
        if col is None:
            return EXPANSION_WEIGHT
        rel = float(self.bm25.idf[col]) / max(self._idf_max, 1e-6)
        return EXPANSION_WEIGHT * min(1.0, max(0.35, rel))

    # ----------------------------------------------------------------- search
    def _raw_scores(self, analysis: QueryAnalysis, query_text: str) -> np.ndarray:
        terms = analysis.tokens + analysis.expansion_tokens
        weights = ([INTENT_WEIGHT if t in INTENT_WORDS else 1.0 for t in analysis.tokens]
                   + [self.expansion_weight(t) for t in analysis.expansion_tokens])
        lex = self.bm25.score(terms, weights)

        char_query = " ".join([query_text] + analysis.expansion_tokens[:10])
        qv = self.char_vec.transform([char_query.lower().replace("ё", "е")])
        fuzzy = np.asarray((self.char_matrix @ qv.T).todense()).ravel().astype(np.float32)

        return self._fuse(lex, fuzzy)

    @staticmethod
    def _rrf_ranks(scores: np.ndarray, limit: int) -> dict[int, int]:
        nz = np.flatnonzero(scores > 0)
        if nz.size == 0:
            return {}
        order = nz[np.argsort(-scores[nz])][:limit]
        return {int(idx): rank for rank, idx in enumerate(order)}

    def _fuse(self, lex: np.ndarray, fuzzy: np.ndarray, limit: int = 400) -> np.ndarray:
        lex_rank = self._rrf_ranks(lex, limit)
        fuz_rank = self._rrf_ranks(fuzzy, limit)
        fused = np.zeros(len(lex), dtype=np.float32)
        for idx, rank in lex_rank.items():
            fused[idx] += 1.0 / (RRF_K + rank)
        for idx, rank in fuz_rank.items():
            fused[idx] += 0.75 / (RRF_K + rank)
        # вес секции: попадание в «Название» важнее, чем в «Порядок обращения»
        nz = fused > 0
        fused[nz] *= self.chunk_weight[nz] / 1.6 + 0.4
        return fused

    def _allowed_services(self, filters: SearchFilters) -> set[str] | None:
        if filters.is_empty():
            return None
        allowed: set[str] | None = None

        def narrow(candidate: set[str]) -> None:
            nonlocal allowed
            allowed = candidate if allowed is None else (allowed & candidate)

        if filters.service_ids is not None:
            narrow(set(filters.service_ids))
        if filters.departments:
            want = set(filters.departments)
            narrow({sid for sid, s in self.services.items() if s["department_id"] in want})
        if filters.life_situations:
            want = set(filters.life_situations)
            narrow({sid for sid, s in self.services.items()
                    if want & set(s["life_situation_ids"])})
        if filters.recipients:
            want = set(filters.recipients)
            narrow({sid for sid, s in self.services.items()
                    if want & set(s["recipient_ids"])})
        if filters.branches:
            want = set(filters.branches)
            narrow({sid for sid, s in self.services.items()
                    if want & set(s["branch_ids"])})
        return allowed or set()

    def search_chunks(
        self,
        query: str,
        analysis: QueryAnalysis | None = None,
        filters: SearchFilters | None = None,
        top_k: int = 12,
        per_service: int = 3,
    ) -> tuple[list[ChunkHit], QueryAnalysis]:
        analysis = analysis or self.analyze(query)
        scores = self._raw_scores(analysis, analysis.normalized)
        allowed = self._allowed_services(filters or SearchFilters())

        nz = np.flatnonzero(scores > 0)
        if nz.size == 0:
            return [], analysis
        order = nz[np.argsort(-scores[nz])]

        hits: list[ChunkHit] = []
        per_service_count: dict[str, int] = {}
        for idx in order:
            sid = self.chunk_service[idx]
            if allowed is not None and sid not in allowed:
                continue
            if per_service_count.get(sid, 0) >= per_service:
                continue
            per_service_count[sid] = per_service_count.get(sid, 0) + 1
            ch = self.chunks[idx]
            hits.append(ChunkHit(
                chunk_index=int(idx), chunk_id=ch["chunkId"], service_id=sid,
                section=ch["section"], section_label=ch["sectionLabel"],
                text=ch["text"], score=float(scores[idx]),
            ))
            if len(hits) >= top_k:
                break
        return hits, analysis

    def search_services(
        self,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 20,
    ) -> tuple[list[ServiceHit], QueryAnalysis]:
        analysis = self.analyze(query)
        if not analysis.tokens and not analysis.expansion_tokens:
            return [], analysis
        scores = self._raw_scores(analysis, analysis.normalized)
        allowed = self._allowed_services(filters or SearchFilters())

        # канал названий услуг
        terms = analysis.tokens + analysis.expansion_tokens
        weights = ([INTENT_WEIGHT if t in INTENT_WORDS else 1.0 for t in analysis.tokens]
                   + [self.expansion_weight(t) for t in analysis.expansion_tokens])
        title_scores = self.title_bm25.score(terms, weights)
        title_rank = self._rrf_ranks(title_scores, 200)
        title_bonus: dict[str, float] = {
            self.service_order[i]: 1.0 / (RRF_K + r) for i, r in title_rank.items()
        }

        agg: dict[str, list[tuple[float, int]]] = {}
        nz = np.flatnonzero(scores > 0)
        if nz.size == 0 and not title_bonus:
            return [], analysis
        for idx in nz[np.argsort(-scores[nz])][:1500]:
            sid = self.chunk_service[idx]
            if allowed is not None and sid not in allowed:
                continue
            agg.setdefault(sid, []).append((float(scores[idx]), int(idx)))
        for sid in title_bonus:
            if allowed is not None and sid not in allowed:
                continue
            agg.setdefault(sid, [])

        results: list[ServiceHit] = []
        for sid, items in agg.items():
            items.sort(reverse=True)
            if items:
                best, best_idx = items[0]
            else:
                pos = self.by_service.get(sid, [])
                if not pos:
                    continue
                best, best_idx = 0.0, pos[0]
            # основной вклад — лучший фрагмент; остальные добавляют «полноту» ответа
            total = best + sum(sc for sc, _ in items[1:4]) * 0.35
            total += TITLE_CHANNEL_WEIGHT * title_bonus.get(sid, 0.0)
            svc = self.services[sid]
            # бонус за точное вхождение фразы запроса в название
            if analysis.tokens:
                title_lemmas = set(normalize_text(svc["title"]))
                overlap = len(set(analysis.tokens) & title_lemmas) / len(set(analysis.tokens))
                total *= 1.0 + 0.85 * overlap
            # услуги с почти пустой карточкой не должны выигрывать у полных
            total *= 0.75 + 0.25 * svc["completeness"]
            ch = self.chunks[best_idx]
            results.append(ServiceHit(
                service_id=sid, score=total,
                best_section=ch["section"], best_chunk=ch["chunkId"],
                snippet=ch["text"],
                matched_sections=sorted({self.chunks[i]["section"] for _, i in items[:5]}),
                chunk_hits=[ChunkHit(
                    chunk_index=i, chunk_id=self.chunks[i]["chunkId"], service_id=sid,
                    section=self.chunks[i]["section"],
                    section_label=self.chunks[i]["sectionLabel"],
                    text=self.chunks[i]["text"], score=sc,
                ) for sc, i in items[:3]],
            ))
        results.sort(key=lambda r: -r.score)
        return results[:limit], analysis

    def similar_services(self, service_id: str, limit: int = 6) -> list[str]:
        svc = self.services.get(service_id)
        if not svc:
            return []
        query = f"{svc['title']} {' '.join(svc['life_situations'])}"
        hits, _ = self.search_services(query, limit=limit + 1)
        return [h.service_id for h in hits if h.service_id != service_id][:limit]


def highlight(text: str, analysis: QueryAnalysis, max_len: int = 320) -> str:
    """Возвращает фрагмент вокруг первого совпадения с <mark>-разметкой."""
    from .normalize import lemma

    tokens = set(analysis.tokens) | set(analysis.expansion_tokens[:10])
    if not tokens:
        return text[:max_len]
    words = list(tokenize(text))
    if not words:
        return text[:max_len]
    lows = text.lower().replace("ё", "е")
    pos = -1
    for w in words:
        if lemma(w) in tokens:
            pos = lows.find(w)
            break
    if pos < 0:
        return text[:max_len]
    start = max(0, pos - max_len // 3)
    end = min(len(text), start + max_len)
    frag = text[start:end]
    if start > 0:
        frag = "…" + frag
    if end < len(text):
        frag = frag + "…"
    return frag
