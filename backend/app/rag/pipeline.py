"""RAG-конвейер: поиск фрагментов -> ответ со ссылками на оригинал.

Конвейер:
  1. Разбор запроса (сокращения, раскладка, опечатки).
  2. Определение «намерения» — какой раздел карточки спрашивают.
  3. Гибридный поиск фрагментов (при необходимости — в рамках одной услуги).
  4. Проверка кэша по паре (услуга, нормализованный вопрос).
  5. Генерация ответа LLM либо выдержки в автономном режиме.
  6. Разбор ссылок [n] в ответе -> список источников с якорями на разделы
     карточки и на исходный HTML-текст.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..config import get_settings
from ..index_store import IndexStore, get_store
from ..ingest.schema import SECTIONS
from ..search.hybrid import ChunkHit, SearchFilters
from ..search.normalize import QueryAnalysis, normalize_text
from .cache import AnswerCache
from .llm import LLMClient, LLMResult

RE_CITATION = re.compile(r"\[(\d{1,2})\]")

# Слова-триггеры разделов: если вопрос явно про срок/стоимость, поднимаем
# соответствующий раздел в выдаче фрагментов.
INTENT_SECTIONS: dict[str, tuple[str, ...]] = {
    spec.code: spec.question_words for spec in SECTIONS
}


@dataclass
class Fragment:
    service_id: str
    service_title: str
    service_short: str
    department: str | None
    section: str
    section_label: str
    text: str
    chunk_id: str
    score: float

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "serviceTitle": self.service_title,
            "department": self.department,
            "sectionLabel": self.section_label,
            "text": self.text,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "serviceTitle": self.service_title,
            "serviceShort": self.service_short,
            "department": self.department,
            "section": self.section,
            "sectionLabel": self.section_label,
            "text": self.text,
            "chunkId": self.chunk_id,
            "score": round(self.score, 4),
        }


@dataclass
class RagAnswer:
    answer: str
    fragments: list[Fragment]
    citations: list[int]
    analysis: QueryAnalysis
    mode: str
    cached: bool = False
    model: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    detected_intent: str | None = None
    services: list[dict] = field(default_factory=list)
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "fragments": [f.to_dict() for f in self.fragments],
            "citations": self.citations,
            "analysis": self.analysis.to_dict(),
            "mode": self.mode,
            "cached": self.cached,
            "model": self.model,
            "latencyMs": self.latency_ms,
            "tokensIn": self.tokens_in,
            "tokensOut": self.tokens_out,
            "detectedIntent": self.detected_intent,
            "services": self.services,
            "warning": self.warning,
        }


def detect_intent(analysis: QueryAnalysis) -> str | None:
    """Грубое определение раздела карточки по словам вопроса."""
    tokens = set(analysis.tokens)
    best, best_score = None, 0
    for code, words in INTENT_SECTIONS.items():
        if code == "title":
            continue
        score = len(tokens & set(words))
        if score > best_score:
            best, best_score = code, score
    return best if best_score else None


class RagPipeline:
    def __init__(self, store: IndexStore | None = None) -> None:
        self.store = store or get_store()
        self.settings = get_settings()
        self.llm = LLMClient()
        self.cache = AnswerCache(self.settings.cache_db, self.settings.cache_ttl_days)

    # ------------------------------------------------------------- фрагменты
    def retrieve(
        self, question: str, service_id: str | None = None,
        top_k: int | None = None, filters: SearchFilters | None = None,
    ) -> tuple[list[Fragment], QueryAnalysis, str | None]:
        top_k = top_k or self.settings.top_k_chunks
        searcher = self.store.searcher
        analysis = searcher.analyze(question)
        intent = detect_intent(analysis)

        if service_id:
            filters = SearchFilters(service_ids=[service_id])
            per_service = top_k
        else:
            per_service = 3

        hits, analysis = searcher.search_chunks(
            question, analysis=analysis, filters=filters,
            top_k=top_k * 2, per_service=per_service,
        )

        # Если вопрос явно про раздел (срок/стоимость), а раздела нет среди
        # найденных фрагментов конкретной услуги — добираем его принудительно.
        if service_id and intent:
            have = {h.section for h in hits}
            if intent not in have:
                for idx in searcher.by_service.get(service_id, []):
                    ch = searcher.chunks[idx]
                    if ch["section"] == intent:
                        hits.insert(0, ChunkHit(
                            chunk_index=idx, chunk_id=ch["chunkId"],
                            service_id=service_id, section=ch["section"],
                            section_label=ch["sectionLabel"], text=ch["text"],
                            score=0.0,
                        ))
                        break

        # Приоритет раздела, соответствующего намерению
        if intent:
            hits.sort(key=lambda h: (h.section != intent, -h.score))

        fragments: list[Fragment] = []
        for h in hits[:top_k]:
            svc = self.store.service(h.service_id)
            if not svc:
                continue
            fragments.append(Fragment(
                service_id=h.service_id, service_title=svc["title"],
                service_short=svc["short_title"], department=svc["department"],
                section=h.section, section_label=h.section_label,
                text=h.text, chunk_id=h.chunk_id, score=h.score,
            ))
        return fragments, analysis, intent

    # ------------------------------------------------------------------ ответ
    def ask(
        self, question: str, service_id: str | None = None,
        use_cache: bool = True, filters: SearchFilters | None = None,
    ) -> RagAnswer:
        t0 = time.perf_counter()
        fragments, analysis, intent = self.retrieve(question, service_id, filters=filters)

        kind = "service" if service_id else "global"
        key, norm = AnswerCache.make_key(
            kind, question, self.llm.mode + ":" + self.settings.llm_model,
            self.settings.prompt_version, service_id,
            extra=",".join(sorted({f.service_id for f in fragments})[:5]),
        )

        if use_cache:
            hit = self.cache.get(key)
            if hit:
                self.cache.log_question(kind, question, service_id, cached=True)
                answer = self._from_payload(hit, fragments, analysis, intent)
                answer.latency_ms = int((time.perf_counter() - t0) * 1000)
                return answer

        svc_title = self.store.service(service_id)["title"] if service_id else None
        result = self.llm.answer(question, [f.to_prompt_dict() for f in fragments], svc_title)

        answer = self._build(result, fragments, analysis, intent, question)
        answer.latency_ms = int((time.perf_counter() - t0) * 1000)

        if use_cache and answer.answer:
            self.cache.put(
                key, kind, question, norm,
                self.llm.mode + ":" + self.settings.llm_model,
                self.settings.prompt_version,
                {"answer": answer.answer, "mode": answer.mode, "model": answer.model,
                 "fragments": [f.to_dict() for f in fragments],
                 "citations": answer.citations, "warning": answer.warning},
                service_id=service_id, tokens_in=result.tokens_in,
                tokens_out=result.tokens_out, latency_ms=result.latency_ms,
            )
        self.cache.log_question(kind, question, service_id, cached=False)
        return answer

    def ask_stream(
        self, question: str, service_id: str | None = None, use_cache: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Генератор SSE-событий для чата."""
        t0 = time.perf_counter()
        fragments, analysis, intent = self.retrieve(question, service_id)

        kind = "service" if service_id else "global"
        key, norm = AnswerCache.make_key(
            kind, question, self.llm.mode + ":" + self.settings.llm_model,
            self.settings.prompt_version, service_id,
            extra=",".join(sorted({f.service_id for f in fragments})[:5]),
        )

        yield {"type": "meta", "analysis": analysis.to_dict(),
               "detectedIntent": intent,
               "fragments": [f.to_dict() for f in fragments],
               "mode": self.llm.mode}

        if use_cache:
            hit = self.cache.get(key)
            if hit:
                self.cache.log_question(kind, question, service_id, cached=True)
                yield {"type": "delta", "text": hit["answer"]}
                yield {"type": "done", "cached": True, "mode": hit.get("mode"),
                       "model": hit.get("model", ""),
                       "citations": hit.get("citations", []),
                       "latencyMs": int((time.perf_counter() - t0) * 1000),
                       "cacheHits": hit.get("cacheHits", 1)}
                return

        svc_title = self.store.service(service_id)["title"] if service_id else None
        final: LLMResult | None = None
        for kind_ev, payload in self.llm.answer_stream(
            question, [f.to_prompt_dict() for f in fragments], svc_title
        ):
            if kind_ev == "delta":
                yield {"type": "delta", "text": payload}
            else:
                final = payload

        if final is None:
            yield {"type": "done", "cached": False, "mode": self.llm.mode}
            return

        answer = self._build(final, fragments, analysis, intent, question)
        if use_cache and answer.answer:
            self.cache.put(
                key, kind, question, norm,
                self.llm.mode + ":" + self.settings.llm_model,
                self.settings.prompt_version,
                {"answer": answer.answer, "mode": answer.mode, "model": answer.model,
                 "fragments": [f.to_dict() for f in fragments],
                 "citations": answer.citations, "warning": answer.warning},
                service_id=service_id, tokens_in=final.tokens_in,
                tokens_out=final.tokens_out, latency_ms=final.latency_ms,
            )
        self.cache.log_question(kind, question, service_id, cached=False)
        yield {"type": "done", "cached": False, "mode": answer.mode,
               "model": answer.model, "citations": answer.citations,
               "warning": answer.warning,
               "tokensIn": final.tokens_in, "tokensOut": final.tokens_out,
               "latencyMs": int((time.perf_counter() - t0) * 1000)}

    # ----------------------------------------------------------------- сборка
    def _build(
        self, result: LLMResult, fragments: list[Fragment],
        analysis: QueryAnalysis, intent: str | None, question: str,
    ) -> RagAnswer:
        citations = sorted({
            int(m) for m in RE_CITATION.findall(result.text)
            if 1 <= int(m) <= len(fragments)
        })
        warning = None
        if result.error:
            warning = f"LLM недоступна ({result.error}). Показан автономный ответ."
        elif result.mode == "llm" and not citations and fragments:
            warning = "В ответе нет ссылок на источники — проверьте по карточке услуги."

        services: list[dict] = []
        seen: set[str] = set()
        for f in fragments:
            if f.service_id in seen:
                continue
            seen.add(f.service_id)
            services.append({
                "id": f.service_id, "title": f.service_title,
                "shortTitle": f.service_short, "department": f.department,
            })

        return RagAnswer(
            answer=result.text, fragments=fragments, citations=citations,
            analysis=analysis, mode=result.mode, model=result.model,
            tokens_in=result.tokens_in, tokens_out=result.tokens_out,
            detected_intent=intent, services=services, warning=warning,
        )

    def _from_payload(
        self, payload: dict, fragments: list[Fragment],
        analysis: QueryAnalysis, intent: str | None,
    ) -> RagAnswer:
        cached_fragments = [
            Fragment(
                service_id=f["serviceId"], service_title=f["serviceTitle"],
                service_short=f["serviceShort"], department=f.get("department"),
                section=f["section"], section_label=f["sectionLabel"],
                text=f["text"], chunk_id=f["chunkId"], score=f.get("score", 0.0),
            ) for f in payload.get("fragments", [])
        ] or fragments
        services: list[dict] = []
        seen: set[str] = set()
        for f in cached_fragments:
            if f.service_id in seen:
                continue
            seen.add(f.service_id)
            services.append({
                "id": f.service_id, "title": f.service_title,
                "shortTitle": f.service_short, "department": f.department,
            })
        return RagAnswer(
            answer=payload["answer"], fragments=cached_fragments,
            citations=payload.get("citations", []), analysis=analysis,
            mode=payload.get("mode", "llm"), cached=True,
            model=payload.get("model", ""), detected_intent=intent,
            services=services, warning=payload.get("warning"),
        )


_pipeline: RagPipeline | None = None


def get_pipeline() -> RagPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RagPipeline()
    return _pipeline
