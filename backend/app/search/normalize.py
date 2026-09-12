"""Нормализация запросов и текстов: морфология, раскладка, сокращения.

Оператор МФЦ пишет запрос в окне быстро и «как думает»: «снилс ребенку»,
«скок стоит загран», «ghjgbcrf» (набрано в латинской раскладке), «мат капитал».
Модуль приводит такой ввод к тем же леммам, которыми проиндексирована
база знаний, и расширяет его расшифровками аббревиатур.
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymorphy3

RE_TOKEN = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
RE_NON_WORD = re.compile(r"[^а-яёa-z0-9\s-]", re.IGNORECASE)

# Стоп-слова: служебные части речи + канцелярит, который есть почти в каждой услуге
# и потому не несёт различающего сигнала.
STOPWORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то",
    "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за",
    "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня", "еще",
    "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь",
    "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя",
    "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже",
    "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому",
    "этого", "какой", "совсем", "ним", "здесь", "этом", "один", "почти",
    "мой", "тем", "чтобы", "нее", "были", "куда", "зачем", "всех", "никогда",
    "можно", "при", "наконец", "два", "об", "другой", "хоть", "после", "над",
    "больше", "тот", "через", "эти", "нас", "про", "всего", "них", "какая",
    "много", "разве", "три", "эту", "моя", "впрочем", "хорошо", "свою",
    "этой", "перед", "иногда", "лучше", "чуть", "том", "нельзя", "такой",
    "им", "более", "всегда", "конечно", "всю", "между",
    # канцелярит
    "также", "либо", "случае", "иной", "иных", "данный", "указанный",
}

# Слова-«обёртки» вопроса: несут интонацию, а не предмет услуги. Их вклад
# в BM25 занижаем, иначе редкий глагол перевешивает название услуги.
INTENT_WORDS = {
    "хотеть", "делать", "сделать", "нужно", "нужный", "надо", "мочь", "сказать",
    "подсказать", "какой", "который", "получить", "получение", "оформить",
    "оформление", "сколько", "стоить", "дать", "давать", "взять", "принести",
    "прийти", "приходить", "спросить", "вопрос", "клиент", "заявитель",
    "гражданин", "человек", "случай", "situation",
}

# Подмножество, которое не несёт смысла для КЛЮЧА КЭША. «Сколько» и «стоить»
# сюда не входят: в поиске их вес занижен, но вопрос о стоимости и вопрос
# о документах — это разные вопросы и разные ответы.
CACHE_FILLER_WORDS = {
    "хотеть", "делать", "сделать", "нужно", "нужный", "надо", "мочь", "сказать",
    "подсказать", "какой", "который", "прийти", "приходить", "спросить",
    "вопрос", "клиент", "заявитель", "гражданин", "человек", "случай",
}

# Раскладка ЙЦУКЕН <-> QWERTY: частая ошибка при быстром вводе.
_RU_LAYOUT = "йцукенгшщзхъфывапролджэячсмитьбю.ёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"
_EN_LAYOUT = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~"
EN_TO_RU = str.maketrans(_EN_LAYOUT, _RU_LAYOUT)

_morph = pymorphy3.MorphAnalyzer()


@functools.lru_cache(maxsize=200_000)
def lemma(token: str) -> str:
    """Лемма слова. Кэш обязателен: индексация гоняет миллионы токенов."""
    if len(token) < 3 or token.isdigit():
        return token
    parsed = _morph.parse(token)
    if not parsed:
        return token
    return parsed[0].normal_form.replace("ё", "е")


def tokenize(text: str) -> list[str]:
    return [t.lower().replace("ё", "е") for t in RE_TOKEN.findall(text or "")]


def lemmatize(tokens: list[str], drop_stopwords: bool = True) -> list[str]:
    out: list[str] = []
    for t in tokens:
        if drop_stopwords and t in STOPWORDS:
            continue
        lm = lemma(t)
        if drop_stopwords and lm in STOPWORDS:
            continue
        if len(lm) < 2:
            continue
        out.append(lm)
    return out


def normalize_text(text: str, drop_stopwords: bool = True) -> list[str]:
    return lemmatize(tokenize(text), drop_stopwords=drop_stopwords)


def is_known_word(token: str) -> bool:
    """Слово есть в словаре русского языка (а не опечатка/аббревиатура)."""
    return _morph.word_is_known(token)


def looks_like_wrong_layout(text: str) -> bool:
    """Строка набрана латиницей, но по-русски: «ghjgbcrf» = «прописка».

    Проверки «все буквы латинские» недостаточно: оператор вполне может ввести
    латиницей «egrn» или «mfc», и перекодировка превратила бы это в «учкт».
    Поэтому конвертируем и требуем, чтобы получилось хотя бы одно РЕАЛЬНОЕ
    русское слово по словарю pymorphy.
    """
    letters = [c for c in text.lower() if c.isalpha()]
    if len(letters) < 4:
        return False
    latin = sum(1 for c in letters if "a" <= c <= "z")
    if latin / len(letters) < 0.9:
        return False

    converted = text.translate(EN_TO_RU)
    tokens = [t for t in RE_TOKEN.findall(converted.lower()) if len(t) >= 4]
    if not tokens:
        return False
    return any(is_known_word(t) for t in tokens)


def fix_layout(text: str) -> str:
    return text.translate(EN_TO_RU)


@dataclass
class SynonymEntry:
    terms: list[str]
    expand_to: list[str]
    hint: str = ""


@dataclass
class QueryAnalysis:
    """Результат разбора запроса оператора — показывается в интерфейсе."""

    raw: str
    normalized: str
    tokens: list[str] = field(default_factory=list)
    expansion_tokens: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    layout_fixed: bool = False
    corrections: list[dict[str, str]] = field(default_factory=list)

    @property
    def all_tokens(self) -> list[str]:
        return self.tokens + self.expansion_tokens

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "normalized": self.normalized,
            "tokens": self.tokens,
            "expansionTokens": self.expansion_tokens,
            "hints": self.hints,
            "layoutFixed": self.layout_fixed,
            "corrections": self.corrections,
        }


class SynonymIndex:
    """Поиск аббревиатур/жаргона в запросе по леммам (фразы до 4 слов)."""

    MAX_PHRASE = 4

    def __init__(self, entries: list[SynonymEntry]):
        self.entries = entries
        self._phrases: dict[tuple[str, ...], int] = {}
        for i, entry in enumerate(entries):
            for term in entry.terms:
                key = tuple(normalize_text(term, drop_stopwords=False))
                if key and key not in self._phrases:
                    self._phrases[key] = i

    @classmethod
    def load(cls, path: Path) -> "SynonymIndex":
        if not path.exists():
            return cls([])
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [
            SynonymEntry(
                terms=e.get("terms", []),
                expand_to=e.get("expand_to", []),
                hint=e.get("hint", ""),
            )
            for e in data.get("entries", [])
        ]
        return cls(entries)

    def match(self, lemmas: list[str]) -> list[SynonymEntry]:
        """Жадный поиск самых длинных совпадающих фраз."""
        found: list[SynonymEntry] = []
        seen: set[int] = set()
        i = 0
        while i < len(lemmas):
            hit = None
            for size in range(min(self.MAX_PHRASE, len(lemmas) - i), 0, -1):
                key = tuple(lemmas[i:i + size])
                idx = self._phrases.get(key)
                if idx is not None:
                    hit = (idx, size)
                    break
            if hit:
                idx, size = hit
                if idx not in seen:
                    seen.add(idx)
                    found.append(self.entries[idx])
                i += size
            else:
                i += 1
        return found
