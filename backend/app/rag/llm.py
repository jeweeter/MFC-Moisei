"""Обёртка над Anthropic Claude + автономный (extractive) режим.

Система обязана работать, даже если ключа API нет или внешний доступ закрыт:
в этом случае Моисей не «сочиняет» ответ, а собирает его выдержками из
найденных фрагментов. Для оператора это по-прежнему полезно (он получает
нужный раздел регламента за секунду), а для демонстрации — гарантирует,
что приложение запускается «из коробки».
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..config import get_settings
from .prompts import (
    SYSTEM_ANSWER,
    SYSTEM_QUERY_REWRITE,
    SYSTEM_WIZARD,
    build_user_message,
)


@dataclass
class LLMResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = ""
    mode: str = "llm"          # llm | extractive
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        if self.settings.llm_enabled:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
            except Exception:  # pragma: no cover - зависит от окружения
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def mode(self) -> str:
        return "llm" if self.available else "extractive"

    # ------------------------------------------------------------------ ответ
    def answer(
        self, question: str, fragments: list[dict], service_title: str | None = None,
        system: str | None = None,
    ) -> LLMResult:
        if not self.available:
            return extractive_answer(question, fragments)

        t0 = time.perf_counter()
        try:
            resp = self._client.messages.create(
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                system=system or SYSTEM_ANSWER,
                messages=[{
                    "role": "user",
                    "content": build_user_message(question, fragments, service_title),
                }],
            )
        except Exception as exc:  # сеть/квота/ключ — не роняем окно оператора
            fallback = extractive_answer(question, fragments)
            fallback.error = f"{type(exc).__name__}: {exc}"[:300]
            return fallback

        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return LLMResult(
            text=text.strip(),
            tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            model=self.settings.llm_model,
            mode="llm",
        )

    def answer_stream(
        self, question: str, fragments: list[dict], service_title: str | None = None,
        system: str | None = None,
    ) -> Iterator[tuple[str, Any]]:
        """Отдаёт ('delta', текст) ... затем ('done', LLMResult)."""
        if not self.available:
            result = extractive_answer(question, fragments)
            for piece in re.findall(r"[^\n]*\n?", result.text):
                if piece:
                    yield "delta", piece
            yield "done", result
            return

        t0 = time.perf_counter()
        collected: list[str] = []
        try:
            with self._client.messages.stream(
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                system=system or SYSTEM_ANSWER,
                messages=[{
                    "role": "user",
                    "content": build_user_message(question, fragments, service_title),
                }],
            ) as stream:
                for chunk in stream.text_stream:
                    collected.append(chunk)
                    yield "delta", chunk
                final = stream.get_final_message()
            yield "done", LLMResult(
                text="".join(collected).strip(),
                tokens_in=final.usage.input_tokens,
                tokens_out=final.usage.output_tokens,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                model=self.settings.llm_model, mode="llm",
            )
        except Exception as exc:
            result = extractive_answer(question, fragments)
            result.error = f"{type(exc).__name__}: {exc}"[:300]
            if not collected:
                for piece in re.findall(r"[^\n]*\n?", result.text):
                    if piece:
                        yield "delta", piece
            yield "done", result

    def wizard_summary(self, situation: str, services_block: str) -> LLMResult:
        """Памятка оператору по собранному пакету услуг."""
        if not self.available:
            return LLMResult(text="", mode="extractive")
        user = (f"Жизненная ситуация заявителя: {situation}\n\n"
                f"Подобранный пакет услуг:\n{services_block}")
        return self._raw(SYSTEM_WIZARD, user)

    def _raw(self, system: str, user: str) -> LLMResult:
        t0 = time.perf_counter()
        try:
            resp = self._client.messages.create(
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            return LLMResult(text="", mode="extractive", error=str(exc)[:300])
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return LLMResult(
            text=text.strip(), tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            model=self.settings.llm_model, mode="llm",
        )

    def rewrite_query(self, query: str) -> dict[str, Any] | None:
        """Расширение запроса силами LLM (используется, если лексический
        поиск дал слабый результат). Возвращает None в автономном режиме."""
        if not self.available:
            return None
        res = self._raw(SYSTEM_QUERY_REWRITE, query)
        if not res.text:
            return None
        match = re.search(r"\{.*\}", res.text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


# --------------------------------------------------------------- extractive
RE_SENTENCE = re.compile(r"(?<=[.;!?])\s+")


def extractive_answer(question: str, fragments: list[dict]) -> LLMResult:
    """Ответ без генерации: выдержки из самых релевантных фрагментов.

    Это не «заглушка», а рабочий режим для закрытого контура: оператор
    получает точный текст регламента с указанием услуги и раздела.
    """
    if not fragments:
        return LLMResult(
            text=("В базе знаний не нашлось фрагментов по этому вопросу.\n"
                  "Уточните формулировку или проверьте сведения в справочной "
                  "правовой системе."),
            mode="extractive",
        )

    lines: list[str] = []
    by_service: dict[str, list[tuple[int, dict]]] = {}
    for i, f in enumerate(fragments, start=1):
        by_service.setdefault(f["serviceTitle"], []).append((i, f))

    if len(by_service) > 1:
        lines.append(
            f"Автономный режим (без LLM). Найдено {len(fragments)} фрагментов "
            f"в {len(by_service)} услугах — проверьте, о какой идёт речь:"
        )
    else:
        lines.append("Автономный режим (без LLM). Выдержки из базы знаний:")
    lines.append("")

    for title, items in list(by_service.items())[:3]:
        lines.append(f"**{title}**")
        for idx, f in items[:2]:
            snippet = f["text"].strip()
            if len(snippet) > 700:
                cut = snippet[:700]
                dot = cut.rfind("\n")
                snippet = (cut[:dot] if dot > 300 else cut) + "…"
            lines.append(f"_{f['sectionLabel']}_ [{idx}]")
            lines.append(snippet)
            lines.append("")
    lines.append("⚠️ Проверьте: ответ собран выдержками без анализа. "
                 "Сверьтесь с административным регламентом услуги.")
    return LLMResult(text="\n".join(lines).strip(), mode="extractive")
