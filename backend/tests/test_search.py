"""Понимание запроса и поиск."""
import pytest

from app.index_store import get_store
from app.search.normalize import fix_layout, looks_like_wrong_layout, normalize_text


@pytest.fixture(scope="module")
def searcher():
    return get_store().searcher


def test_layout_detection():
    assert looks_like_wrong_layout("ghjgbcrf")
    assert fix_layout("ghjgbcrf") == "прописка"
    # настоящий английский текст не трогаем
    assert not looks_like_wrong_layout("egrn")
    assert not looks_like_wrong_layout("мфц")


def test_morphology_normalizes_word_forms():
    assert normalize_text("документами") == normalize_text("документ")
    assert "паспорт" in normalize_text("паспорта заявителя")


def test_abbreviations_are_expanded_with_hint(searcher):
    a = searcher.analyze("скок стоит выписка егрн")
    assert any("ЕГРН" in h for h in a.hints)
    assert "недвижимость" in a.expansion_tokens or "недвижимый" in a.expansion_tokens


def test_layout_is_fixed_in_analysis(searcher):
    a = searcher.analyze("ghjgbcrf")
    assert a.layout_fixed
    assert a.normalized == "прописка"


def test_typos_are_corrected_but_real_words_are_not(searcher):
    a = searcher.analyze("паспрт")
    assert {"from": "паспрт", "to": "паспорт"} in a.corrections
    # «делать» — обычное слово, которого нет в базе: это не опечатка
    b = searcher.analyze("что делать")
    assert b.corrections == []


@pytest.mark.parametrize(
    "query,expected_substring",
    [
        ("какие документы на загранпаспорт", "за пределами территории"),
        ("справка о несудимости", "судимости"),
        ("банкротство физлица", "банкротом во внесудебном"),
        ("ghjgbcrf", "Регистрационный учет"),
        ("субсидия на коммуналку", "субсидий на оплату жилых помещений"),
    ],
)
def test_known_queries_hit_top3(searcher, query, expected_substring):
    hits, _ = searcher.search_services(query, limit=3)
    titles = [searcher.services[h.service_id]["title"] for h in hits]
    assert any(expected_substring.lower() in t.lower() for t in titles), titles


def test_search_is_fast(searcher):
    import time

    t0 = time.perf_counter()
    for _ in range(10):
        searcher.search_services("документы на загранпаспорт ребенку", limit=20)
    per_query_ms = (time.perf_counter() - t0) / 10 * 1000
    assert per_query_ms < 250, f"{per_query_ms:.0f} мс на запрос"


def test_filters_restrict_results(searcher):
    from app.search.hybrid import SearchFilters

    store = get_store()
    dep = store.departments[0]["id"]
    hits, _ = searcher.search_services(
        "справка", filters=SearchFilters(departments=[dep]), limit=10
    )
    assert hits
    assert all(store.services[h.service_id]["department_id"] == dep for h in hits)


def test_municipal_variants_are_grouped():
    store = get_store()
    groups = store.variant_groups
    assert len(groups) >= 10
    biggest = max(groups.values(), key=len)
    assert len(biggest) >= 20
    # у каждой услуги группы проставлен свой ярлык муниципалитета
    labels = {store.services[sid]["variant_label"] for sid in biggest}
    assert len(labels) == len(biggest)
