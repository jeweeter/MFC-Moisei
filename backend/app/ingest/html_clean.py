"""Очистка HTML-разметки из полей базы знаний mfc71.ru.

Исходные поля db_knowledge содержат текст, вставленный из MS Word через
визуальный редактор. Внутри встречается:
  * инлайн-стили на каждом <span>/<p> (до 90% объёма поля);
  * служебные namespace-теги Word: <o:p>, <w:*>, <m:*>, <xml>;
  * base64-картинки в <img src="data:image/png;base64,...">  (до 800 КБ на поле);
  * html-сущности &nbsp;, &quot;, &#45;;
  * «мусорные» переводы строк \r\n внутри абзацев.

Задача модуля — получить из этого:
  1. `text`  — читаемый плоский текст (для RAG-индекса и для LLM-контекста);
  2. `blocks`— структурированные блоки (абзац / пункт списка / таблица / ссылка),
     чтобы фронтенд рисовал нормальную типографику, а не «простыню»;
  3. `links` — вынесенные наружу гиперссылки;
  4. сохранение исходного HTML (в индексе) — для показа оператору
     «оригинального текста» рядом с ответом ассистента.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Comment, Declaration, NavigableString, ProcessingInstruction, Tag

# Теги, которые целиком выкидываем вместе с содержимым.
DROP_TREES = {"style", "script", "xml", "head", "meta", "link"}
# Word-овские служебные namespace-префиксы: <o:p>, <w:worddocument>, <m:oMath>.
NS_PREFIXES = ("o:", "w:", "m:", "v:", "st1:", "x:")

BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "ol", "ul", "hr", "blockquote",
}

# Маркеры нумерации в начале строки: «1.», «1)», «1.2.», «- », «•», «а)»
RE_NUM_MARKER = re.compile(
    r"^\s*(\d{1,2}(?:\.\d{1,2})*[.)]|[-–—•*]|[а-яa-zё][.)])\s*(?=[\"«A-Za-zА-Яа-яЁё])"
)
RE_MULTISPACE = re.compile(r"[ \t   ]+")
RE_MULTINEWLINE = re.compile(r"\n{3,}")
RE_DATA_URI = re.compile(r"^data:", re.I)
# «Голый» HTML, который иногда лежит в поле как экранированный текст
RE_LOOKS_LIKE_HTML = re.compile(r"&lt;\s*(p|div|span|br|li)\b", re.I)


@dataclass
class CleanBlock:
    """Структурный блок очищенного текста."""

    kind: str  # paragraph | list_item | heading | table_row | rule
    text: str
    level: int = 0
    marker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "text": self.text}
        if self.level:
            d["level"] = self.level
        if self.marker:
            d["marker"] = self.marker
        return d


@dataclass
class CleanResult:
    text: str = ""
    blocks: list[CleanBlock] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    images_dropped: int = 0
    original_length: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "blocks": [b.to_dict() for b in self.blocks],
            "links": self.links,
        }


def _unescape_repeatedly(value: str, limit: int = 3) -> str:
    """&amp;nbsp; встречается в данных — раскодируем до устойчивого состояния."""
    for _ in range(limit):
        new = html.unescape(value)
        if new == value:
            break
        value = new
    return value


def _strip_word_noise(soup: BeautifulSoup) -> int:
    """Удаляет служебные теги Word и base64-картинки. Возвращает число картинок."""
    images = 0
    # Условные комментарии Word (<!--[if gte mso 9]><xml>...<![endif]-->) bs4 отдаёт
    # как Comment; их содержимое иначе попадает в текст мусором.
    for node in soup.find_all(
        string=lambda t: isinstance(t, (Comment, Declaration, ProcessingInstruction))
    ):
        node.extract()
    for tag in soup.find_all(True):
        name = (tag.name or "").lower()
        if name in DROP_TREES or name.startswith(NS_PREFIXES):
            tag.decompose()
            continue
        if name == "img":
            src = tag.get("src") or ""
            if RE_DATA_URI.match(src):
                images += 1
            tag.decompose()
            continue
    return images


def _collect_links(soup: BeautifulSoup) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or RE_DATA_URI.match(href):
            continue
        title = RE_MULTISPACE.sub(" ", a.get_text(" ", strip=True)) or href
        key = f"{href}|{title}"
        if key in seen:
            continue
        seen.add(key)
        links.append({"href": href, "title": title[:200]})
    return links


def _walk(node: Tag | NavigableString, out: list[str]) -> None:
    """Рекурсивно превращает дерево в текст с маркерами переноса блоков."""
    if isinstance(node, NavigableString):
        out.append(str(node))
        return
    if not isinstance(node, Tag):
        return

    name = (node.name or "").lower()
    if name == "br":
        out.append("\n")
        return
    if name == "hr":
        out.append("\n␟\n")  # разделитель секций
        return
    if name == "li":
        out.append("\n•​")  # спец-маркер пункта списка
        for child in node.children:
            _walk(child, out)
        out.append("\n")
        return
    if name in {"td", "th"}:
        for child in node.children:
            _walk(child, out)
        out.append("│")  # разделитель ячеек
        return

    is_block = name in BLOCK_TAGS
    if is_block:
        out.append("\n")
    for child in node.children:
        _walk(child, out)
    if is_block:
        out.append("\n")


def _postprocess(raw_text: str) -> tuple[str, list[CleanBlock]]:
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    raw_text = raw_text.replace("­", "")  # мягкий перенос
    lines: list[str] = []
    for line in raw_text.split("\n"):
        line = RE_MULTISPACE.sub(" ", line).strip()
        line = line.strip("│").strip()
        if line in {"", "​"}:
            lines.append("")
            continue
        lines.append(line)

    blocks: list[CleanBlock] = []
    text_parts: list[str] = []
    for line in lines:
        if not line:
            continue
        if line == "␟":
            if blocks and blocks[-1].kind != "rule":
                blocks.append(CleanBlock(kind="rule", text=""))
            continue

        is_li = line.startswith("•​")
        if is_li:
            line = line[2:].strip()
        if not line:
            continue

        marker = None
        m = RE_NUM_MARKER.match(line)
        if m:
            marker = m.group(1)
            body = line[m.end():].strip()
            if body:
                line = body
                is_li = True

        # Строка-заголовок: короткая, заканчивается двоеточием
        kind = "list_item" if is_li else "paragraph"
        if not is_li and len(line) < 160 and line.endswith(":"):
            kind = "heading"

        if "│" in line:
            kind = "table_row"
            line = " | ".join(p.strip() for p in line.split("│") if p.strip())

        blocks.append(CleanBlock(kind=kind, text=line, marker=marker))
        text_parts.append(f"{marker} {line}" if marker else line)

    # схлопываем дубли подряд идущих одинаковых строк (артефакт Word-таблиц)
    deduped: list[CleanBlock] = []
    for b in blocks:
        if deduped and deduped[-1].text == b.text and b.kind == deduped[-1].kind:
            continue
        deduped.append(b)

    text = "\n".join(
        f"{b.marker} {b.text}" if b.marker else b.text for b in deduped if b.text
    )
    text = RE_MULTINEWLINE.sub("\n\n", text).strip()
    return text, deduped


def clean_html(value: Any) -> CleanResult:
    """Главная точка входа: HTML/текст из базы знаний -> CleanResult."""
    if value is None:
        return CleanResult()
    if not isinstance(value, str):
        value = str(value)

    result = CleanResult(original_length=len(value))
    if not value.strip():
        return result

    # Поле может содержать «дважды экранированный» HTML.
    if RE_LOOKS_LIKE_HTML.search(value):
        value = _unescape_repeatedly(value)

    has_markup = "<" in value and ">" in value
    if has_markup:
        soup = BeautifulSoup(value, "lxml")
        result.images_dropped = _strip_word_noise(soup)
        result.links = _collect_links(soup)
        buf: list[str] = []
        root = soup.body or soup
        for child in root.children:
            _walk(child, buf)
        raw_text = "".join(buf)
    else:
        raw_text = value

    raw_text = _unescape_repeatedly(raw_text)
    result.text, result.blocks = _postprocess(raw_text)
    return result


def clean_to_text(value: Any) -> str:
    """Короткий помощник, когда нужен только плоский текст."""
    return clean_html(value).text
