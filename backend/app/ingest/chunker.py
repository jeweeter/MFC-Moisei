"""Разбиение услуги на цитируемые фрагменты (чанки) для RAG.

Единица цитирования = «услуга + раздел (+ порядковый номер окна)».
Оператор в ответе Моисея видит не «источник: база знаний», а
«Перечень документов, услуга №…», и одним кликом открывает оригинал.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import SECTIONS, FieldSpec

# Целевой размер окна в символах. Подобран так, чтобы:
#  - в контекст LLM влезало 10-14 фрагментов;
#  - типичный «перечень документов» (3.3 КБ в среднем) резался на 3-5 частей,
#    каждая из которых остаётся осмысленным куском списка.
TARGET_CHARS = 900
MAX_CHARS = 1400
OVERLAP_BLOCKS = 1


@dataclass
class Chunk:
    chunk_id: str
    service_id: str
    section: str          # код секции
    section_label: str
    part: int             # номер окна внутри секции (0 если секция целиком)
    parts_total: int
    text: str
    weight: float
    block_start: int      # индекс первого блока секции — якорь для подсветки
    block_end: int
    tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk_id,
            "serviceId": self.service_id,
            "section": self.section,
            "sectionLabel": self.section_label,
            "part": self.part,
            "partsTotal": self.parts_total,
            "text": self.text,
            "blockStart": self.block_start,
            "blockEnd": self.block_end,
        }


def _piece(b: dict[str, Any]) -> str:
    marker = b.get("marker")
    text = b.get("text") or ""
    return f"{marker} {text}" if marker else text


def _window_blocks(blocks: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    """Режет список блоков на окна ~TARGET_CHARS, не разрывая блок.

    Заголовок (kind='heading') прилипает к следующему окну — иначе пункты
    списка теряют смысловую шапку вида «Представитель дополнительно
    представляет:».
    """
    windows: list[tuple[int, int, str]] = []
    if not blocks:
        return windows

    start = 0
    buf: list[str] = []
    size = 0
    i = 0
    while i < len(blocks):
        b = blocks[i]
        piece = _piece(b)
        if not piece:
            i += 1
            continue

        # Не начинать окно с «висячего» заголовка в конце предыдущего.
        if size and size + len(piece) > MAX_CHARS:
            windows.append((start, i - 1, "\n".join(buf)))
            back = max(start, i - OVERLAP_BLOCKS)
            # перенос заголовка вперёд
            while back < i and blocks[back].get("kind") != "heading":
                back += 1
            start = back if back < i else i
            buf = []
            size = 0
            for j in range(start, i):
                pp = _piece(blocks[j])
                buf.append(pp)
                size += len(pp)

        buf.append(piece)
        size += len(piece) + 1
        if size >= TARGET_CHARS and b.get("kind") != "heading":
            windows.append((start, i, "\n".join(buf)))
            start = i + 1
            buf = []
            size = 0
        i += 1

    if buf:
        windows.append((start, len(blocks) - 1, "\n".join(buf)))
    return [w for w in windows if w[2].strip()]


def build_chunks(
    service_id: str,
    title: str,
    sections: dict[str, dict[str, Any]],
) -> list[Chunk]:
    """sections: код секции -> {'text': str, 'blocks': [CleanBlock]}"""
    chunks: list[Chunk] = []

    for spec in SECTIONS:
        sec = sections.get(spec.code)
        if not sec:
            continue
        text: str = sec.get("text") or ""
        if not text.strip():
            continue
        blocks: list[dict[str, Any]] = sec.get("blocks") or []

        if spec.code == "title":
            chunks.append(Chunk(
                chunk_id=f"{service_id}::title",
                service_id=service_id, section="title",
                section_label=spec.label, part=0, parts_total=1,
                text=text, weight=spec.weight, block_start=0, block_end=0,
            ))
            continue

        windows = _window_blocks(blocks) if blocks else [(0, 0, text)]
        total = len(windows)
        for idx, (bs, be, wtext) in enumerate(windows):
            # Название услуги добавляем в текст чанка: иначе фрагмент
            # «1. Паспорт 2. Заявление» неотличим у 700 услуг.
            chunks.append(Chunk(
                chunk_id=f"{service_id}::{spec.code}::{idx}",
                service_id=service_id, section=spec.code,
                section_label=spec.label, part=idx, parts_total=total,
                text=wtext, weight=spec.weight,
                block_start=bs, block_end=be,
            ))
    return chunks


def chunk_search_text(chunk: Chunk, title: str, extra: str = "") -> str:
    """Текст, который реально попадает в поисковый индекс."""
    if chunk.section == "title":
        return f"{title} {extra}"
    return f"{title}\n{chunk.section_label}\n{chunk.text}"


def spec_for(code: str) -> FieldSpec | None:
    for s in SECTIONS:
        if s.code == code:
            return s
    return None
