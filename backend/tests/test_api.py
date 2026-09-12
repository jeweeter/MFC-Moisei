"""Дымовые тесты HTTP API."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_meta_exposes_dictionaries(client):
    m = client.get("/api/meta").json()
    assert m["stats"]["services"] == 732
    assert len(m["departments"]) >= 50
    assert len(m["lifeSituations"]) == 17
    assert m["llm"]["mode"] in ("llm", "extractive")
    # короткие имена ведомств различимы между собой
    shorts = [d["shortName"] for d in m["departments"]]
    assert len(set(shorts)) == len(shorts)


def test_search_returns_analysis_and_results(client):
    r = client.get("/api/search", params={"q": "загран ребенку", "limit": 5}).json()
    assert r["results"]
    assert r["analysis"]["hints"]
    assert all("shortTitle" in x for x in r["results"])
    # сниппет не дублирует заголовок
    for item in r["results"]:
        if item["snippet"]:
            assert item["snippet"].strip() != item["title"].strip()


def test_search_groups_municipal_variants(client):
    grouped = client.get(
        "/api/search", params={"q": "градостроительный план земельного участка",
                               "limit": 10, "groupVariants": "true"}).json()
    raw = client.get(
        "/api/search", params={"q": "градостроительный план земельного участка",
                               "limit": 10, "groupVariants": "false"}).json()
    g_titles = {x["variantGroup"] for x in grouped["results"] if x["variantGroup"]}
    r_titles = [x["variantGroup"] for x in raw["results"] if x["variantGroup"]]
    assert len(g_titles) < len(r_titles)


def test_service_card_and_raw(client):
    sid = client.get("/api/search", params={"q": "загранпаспорт", "limit": 1}
                     ).json()["results"][0]["id"]
    card = client.get(f"/api/services/{sid}").json()
    assert card["sections"]
    assert card["branches"]
    codes = [s["code"] for s in card["sections"]]
    assert "documents" in codes

    raw = client.get(f"/api/services/{sid}/raw/documents").json()
    assert raw["length"] > 0


def test_missing_service_is_404(client):
    assert client.get("/api/services/no-such-id").status_code == 404


def test_ask_returns_fragments_with_sources(client):
    r = client.post("/api/ask", json={"question": "какие документы нужны"}).json()
    assert r["fragments"]
    assert r["answer"]
    assert all(f["serviceId"] and f["sectionLabel"] for f in r["fragments"])


def test_ask_stream_emits_sse(client):
    with client.stream("GET", "/api/ask/stream",
                       params={"q": "срок изготовления паспорта"}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert '"type": "meta"' in body
    assert '"type": "done"' in body


def test_wizard_flow(client):
    scenarios = client.get("/api/wizard/scenarios").json()
    assert len(scenarios) >= 8

    sc = client.get("/api/wizard/scenarios/birth").json()
    assert sc["steps"][0]["options"]

    pkg = client.post("/api/wizard/package", json={
        "scenarioId": "birth",
        "answers": {"docs": ["snils"], "payments": ["once", "mk"]},
    }).json()
    assert pkg["summary"]["servicesCount"] >= 3
    assert pkg["checklist"]["common"]
    # паспорт должен требоваться в большинстве услуг пакета
    top = pkg["checklist"]["common"][0]
    assert "личность" in top["text"].lower()
    assert top["count"] >= 2


def test_quality_report(client):
    q = client.get("/api/quality").json()
    assert q["services"] == 732
    assert 40 < q["noiseRemovedPct"] < 70
    assert len(q["sections"]) == 7
    assert q["noLifeSituation"] > 0


def test_cache_stats_endpoint(client):
    s = client.get("/api/cache/stats").json()
    assert "hitRate" in s and "savedUsd" in s
