"""Кэш ответов и RAG-конвейер, включая режим с настоящей LLM (через мок)."""
import pytest

from app.rag.cache import AnswerCache, normalize_question
from app.rag.llm import LLMResult, extractive_answer
from app.rag.pipeline import RagPipeline, detect_intent
from app.index_store import get_store


# ------------------------------------------------------------------ кэш
def test_question_normalization_collapses_paraphrases():
    a = normalize_question("какие документы нужны на загранпаспорт")
    b = normalize_question("Документы на загранпаспорт?")
    c = normalize_question("загранпаспорт: какие документы")
    assert a == b == c


def test_different_intents_get_different_keys():
    docs = normalize_question("какие документы на загранпаспорт")
    price = normalize_question("сколько стоит загранпаспорт")
    term = normalize_question("срок изготовления загранпаспорта")
    assert len({docs, price, term}) == 3


def test_cache_roundtrip_and_stats(tmp_path):
    cache = AnswerCache(tmp_path / "c.sqlite3", ttl_days=30)
    key, norm = AnswerCache.make_key("service", "какие документы?", "m", "v1", "S1")

    assert cache.get(key) is None
    cache.put(key, "service", "какие документы?", norm, "m", "v1",
              {"answer": "Паспорт [1]"}, service_id="S1",
              tokens_in=6000, tokens_out=300, latency_ms=4200)

    hit = cache.get(key)
    assert hit["answer"] == "Паспорт [1]"
    assert hit["cached"] is True

    # тот же вопрос другими словами -> тот же ключ
    key2, _ = AnswerCache.make_key("service", "Документы какие?", "m", "v1", "S1")
    assert key2 == key

    stats = cache.stats(price_in=3.0, price_out=15.0)
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert stats["savedTokensIn"] == 6000
    assert stats["savedUsd"] == pytest.approx(6000 / 1e6 * 3 + 300 / 1e6 * 15)
    assert stats["savedSeconds"] == 4.2


def test_cache_is_invalidated_by_model_or_prompt_version():
    base = AnswerCache.make_key("service", "q", "model-a", "v1", "S1")[0]
    assert AnswerCache.make_key("service", "q", "model-b", "v1", "S1")[0] != base
    assert AnswerCache.make_key("service", "q", "model-a", "v2", "S1")[0] != base
    assert AnswerCache.make_key("service", "q", "model-a", "v1", "S2")[0] != base


# ------------------------------------------------------------- извлечение
def test_extractive_answer_marks_mode_and_warns():
    res = extractive_answer("документы?", [{
        "serviceTitle": "Услуга A", "department": "ФНС",
        "sectionLabel": "Перечень документов", "text": "1. Паспорт",
    }])
    assert res.mode == "extractive"
    assert "Услуга A" in res.text
    assert "⚠️" in res.text


def test_extractive_answer_without_fragments_says_so():
    res = extractive_answer("непонятный вопрос", [])
    assert "не нашлось" in res.text.lower()


# ------------------------------------------------------------------ RAG
@pytest.fixture(scope="module")
def pipeline():
    return RagPipeline(store=get_store())


def test_intent_detection(pipeline):
    s = pipeline.store.searcher
    assert detect_intent(s.analyze("сколько стоит госпошлина")) == "payment"
    assert detect_intent(s.analyze("какие документы принести")) == "documents"
    assert detect_intent(s.analyze("сколько дней ждать")) == "term"


def test_retrieval_is_scoped_to_service(pipeline):
    sid = next(iter(pipeline.store.services))
    frags, _, _ = pipeline.retrieve("документы", service_id=sid)
    assert frags
    assert {f.service_id for f in frags} == {sid}


def test_intent_section_is_pulled_in_even_if_not_top_match(pipeline):
    # услуга с заполненной стоимостью
    sid = next(
        s["id"] for s in pipeline.store.services.values() if "payment" in s["sections"]
    )
    frags, _, intent = pipeline.retrieve("сколько стоит", service_id=sid)
    assert intent == "payment"
    assert frags[0].section == "payment"


class FakeLLM:
    """Заглушка Anthropic: проверяем ветку с настоящей генерацией без ключа."""

    available = True
    mode = "llm"

    def __init__(self):
        self.calls = 0

    def answer(self, question, fragments, service_title=None, system=None):
        self.calls += 1
        return LLMResult(
            text="Нужен паспорт [1] и заявление [2].",
            tokens_in=5200, tokens_out=180, latency_ms=3100,
            model="fake-model", mode="llm",
        )


def test_llm_answer_parses_citations_and_is_cached(tmp_path, pipeline):
    pipe = RagPipeline(store=pipeline.store)
    pipe.llm = FakeLLM()
    pipe.cache = AnswerCache(tmp_path / "rag.sqlite3", ttl_days=30)

    first = pipe.ask("какие документы нужны на загранпаспорт")
    assert first.mode == "llm"
    assert first.cached is False
    assert first.citations == [1, 2]
    assert first.model == "fake-model"
    assert len(first.fragments) > 2
    assert pipe.llm.calls == 1

    second = pipe.ask("документы на загранпаспорт?")
    assert second.cached is True
    assert second.answer == first.answer
    assert pipe.llm.calls == 1, "повторный вопрос не должен идти в LLM"

    stats = pipe.cache.stats(3.0, 15.0)
    assert stats["hits"] == 1
    assert stats["savedTokensIn"] == 5200


def test_llm_failure_falls_back_to_extractive(tmp_path, pipeline):
    class BrokenLLM(FakeLLM):
        def answer(self, question, fragments, service_title=None, system=None):
            res = extractive_answer(question, fragments)
            res.error = "APIConnectionError: no route to host"
            return res

    pipe = RagPipeline(store=pipeline.store)
    pipe.llm = BrokenLLM()
    pipe.cache = AnswerCache(tmp_path / "broken.sqlite3", ttl_days=30)

    ans = pipe.ask("документы на загранпаспорт")
    assert ans.mode == "extractive"
    assert ans.warning and "LLM недоступна" in ans.warning
    assert ans.answer, "оператор всё равно должен получить текст из базы"
