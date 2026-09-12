"""HTTP API помощника оператора «Моисей»."""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..ingest.build_index import short_department
from ..index_store import get_store
from ..ingest.schema import SECTIONS
from ..rag.pipeline import get_pipeline
from ..search.hybrid import SearchFilters, highlight
from ..wizard.situations import get_wizard
from .models import AskRequest, WizardRequest

router = APIRouter(prefix="/api")


def _filters(
    department: list[str] | None, lifeSituation: list[str] | None,
    recipient: list[str] | None, branch: list[str] | None,
) -> SearchFilters:
    return SearchFilters(
        departments=department or [], life_situations=lifeSituation or [],
        recipients=recipient or [], branches=branch or [],
    )


# --------------------------------------------------------------------- мета
@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "ts": time.time()}


@router.get("/meta")
def meta() -> dict[str, Any]:
    store = get_store()
    pipeline = get_pipeline()
    s = get_settings()
    return {
        "app": {"name": "Моисей", "subtitle": "помощник оператора МФЦ",
                "region": "Тульская область"},
        "stats": store.stats(),
        "llm": {
            "enabled": pipeline.llm.available,
            "mode": pipeline.llm.mode,
            "model": s.llm_model if pipeline.llm.available else None,
        },
        "sections": [
            {"code": sp.code, "label": sp.label, "short": sp.short, "icon": sp.icon}
            for sp in SECTIONS
        ],
        "departments": [
            {**d, "shortName": short_department(d["name"])} for d in store.departments
        ],
        "lifeSituations": store.life_situations,
        "recipients": store.recipients,
        "branchesCount": len([b for b in store.branches if b["count"]]),
    }


@router.get("/branches")
def branches(q: str = "", limit: int = 200) -> list[dict[str, Any]]:
    store = get_store()
    items = [b for b in store.branches if b["count"]]
    if q:
        low = q.lower()
        items = [b for b in items
                 if low in (b["name"] or "").lower() or low in (b["address"] or "").lower()]
    return items[:limit]


# ------------------------------------------------------------------- поиск
@router.get("/search")
def search(
    q: str = Query(default="", max_length=500),
    limit: int = Query(default=20, ge=1, le=50),
    groupVariants: bool = Query(default=True),
    department: list[str] | None = Query(default=None),
    lifeSituation: list[str] | None = Query(default=None),
    recipient: list[str] | None = Query(default=None),
    branch: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    store = get_store()
    filters = _filters(department, lifeSituation, recipient, branch)
    t0 = time.perf_counter()

    if not q.strip():
        # Пустой запрос при активных фильтрах = просмотр каталога
        allowed = store.searcher._allowed_services(filters)
        ids = sorted(allowed) if allowed is not None else list(store.services)[:limit]
        items = []
        for sid in ids[:limit]:
            svc = store.services[sid]
            items.append(_service_brief(svc, snippet=svc["short_title"], sections=[]))
        return {"query": q, "total": len(ids), "took": 0,
                "analysis": None, "results": items}

    # Ищем с запасом: часть результатов схлопнется в муниципальные группы.
    hits, analysis = store.searcher.search_services(
        q, filters=filters, limit=limit * 4 if groupVariants else limit
    )
    results: list[dict[str, Any]] = []
    seen_groups: dict[str, dict[str, Any]] = {}
    for h in hits:
        svc = store.services[h.service_id]
        group = svc.get("variant_group") if groupVariants else None
        if group and group in seen_groups:
            seen_groups[group]["variantCount"] += 1
            continue
        # Если лучший фрагмент — само название, показываем в сниппете
        # содержательный раздел: повторять заголовок под заголовком бессмысленно.
        snippet_hit = next(
            (c for c in h.chunk_hits if c.section != "title"), None
        )
        item = _service_brief(
            svc,
            snippet=highlight(snippet_hit.text, analysis) if snippet_hit else "",
            sections=h.matched_sections,
            score=h.score,
            best_section=snippet_hit.section if snippet_hit else h.best_section,
        )
        if group:
            item["variantCount"] = 1
            item["variantTotal"] = len(store.variant_groups.get(group, []))
            seen_groups[group] = item
        results.append(item)
        if len(results) >= limit:
            break
    return {
        "query": q,
        "total": len(hits),
        "took": round((time.perf_counter() - t0) * 1000, 1),
        "analysis": analysis.to_dict(),
        "results": results,
    }


@router.get("/suggest")
def suggest(q: str = Query(min_length=2, max_length=200), limit: int = 8) -> list[dict[str, Any]]:
    store = get_store()
    hits, _ = store.searcher.search_services(q, limit=limit)
    return [{
        "id": h.service_id,
        "title": store.services[h.service_id]["short_title"],
        "department": store.services[h.service_id]["department"],
    } for h in hits]


def _service_brief(svc: dict, snippet: str, sections: list[str],
                   score: float = 0.0, best_section: str | None = None) -> dict[str, Any]:
    return {
        "variantGroup": svc.get("variant_group"),
        "variantLabel": svc.get("variant_label") or None,
        "id": svc["id"],
        "title": svc["title"],
        "shortTitle": svc["short_title"],
        "department": svc["department"],
        "departmentId": svc["department_id"],
        "recipients": svc["recipients"],
        "lifeSituations": svc["life_situations"],
        "branchCount": svc["branch_count"],
        "completeness": svc["completeness"],
        "missingSections": svc["missing_sections"],
        "flags": svc["flags"],
        "snippet": snippet,
        "matchedSections": sections,
        "bestSection": best_section,
        "score": round(score, 4),
    }


# ---------------------------------------------------------------- карточка
@router.get("/services/{service_id}")
def service_card(service_id: str) -> dict[str, Any]:
    store = get_store()
    svc = store.service(service_id)
    if not svc:
        raise HTTPException(status_code=404, detail="Услуга не найдена")

    branches = []
    for bid in svc["branch_ids"][:400]:
        b = store.branch(bid)
        if b:
            branches.append({
                "id": bid, "name": b.get("name"), "address": b.get("address"),
                "schedule": b.get("schedule") or [], "code": b.get("code"),
                "windowCount": b.get("windowCount"),
            })

    order = [sp.code for sp in SECTIONS]
    sections = [
        {"code": code, **svc["sections"][code]}
        for code in order if code in svc["sections"] and code != "title"
    ]
    return {
        **_service_brief(svc, snippet="", sections=[]),
        "sections": sections,
        "branches": branches,
        "similar": store.searcher.similar_services(service_id, limit=6),
        "variants": store.variants_of(service_id),
        "hasRaw": sorted(svc["raw_sections"].keys()),
    }


@router.get("/services/{service_id}/raw/{section}")
def service_raw(service_id: str, section: str) -> dict[str, Any]:
    """Исходный HTML раздела — «оригинальный текст» для сверки оператором."""
    store = get_store()
    svc = store.service(service_id)
    if not svc:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    raw = svc["raw_sections"].get(section)
    if raw is None:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    return {"serviceId": service_id, "section": section, "raw": raw,
            "length": len(raw)}


@router.get("/services/{service_id}/similar")
def service_similar(service_id: str, limit: int = 6) -> list[dict[str, Any]]:
    store = get_store()
    if not store.service(service_id):
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    out = []
    for sid in store.searcher.similar_services(service_id, limit=limit):
        svc = store.services[sid]
        out.append({"id": sid, "shortTitle": svc["short_title"],
                    "department": svc["department"]})
    return out


# -------------------------------------------------------------------- чат
@router.post("/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    pipeline = get_pipeline()
    answer = pipeline.ask(req.question, req.serviceId, use_cache=req.useCache)
    return answer.to_dict()


@router.get("/ask/stream")
def ask_stream(
    q: str = Query(min_length=1, max_length=2000),
    serviceId: str | None = None,
    useCache: bool = True,
) -> StreamingResponse:
    pipeline = get_pipeline()

    def gen() -> Iterator[str]:
        try:
            for event in pipeline.ask_stream(q, serviceId, use_cache=useCache):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # поток не должен обрываться молча
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


# ------------------------------------------------------------------ мастер
@router.get("/wizard/scenarios")
def wizard_scenarios() -> list[dict[str, Any]]:
    return get_wizard().list_scenarios()


@router.get("/wizard/scenarios/{scenario_id}")
def wizard_scenario(scenario_id: str) -> dict[str, Any]:
    sc = get_wizard().scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    return sc


@router.post("/wizard/package")
def wizard_package(req: WizardRequest) -> dict[str, Any]:
    wizard = get_wizard()
    pkg = wizard.build_package(req.scenarioId, req.answers)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Сценарий не найден")

    pipeline = get_pipeline()
    memo = ""
    if req.withMemo and pipeline.llm.available and pkg["services"]:
        from ..rag.cache import AnswerCache

        signature = ",".join(s["id"] for s in pkg["services"])
        key, norm = AnswerCache.make_key(
            "wizard", f"{req.scenarioId} {signature}",
            "llm:" + get_settings().llm_model, get_settings().prompt_version,
        )
        cached = pipeline.cache.get(key)
        if cached:
            memo = cached["answer"]
            pkg["memoCached"] = True
        else:
            block = "\n".join(
                f"[{i}] {s['title']} — ведомство: {s['department'] or 'не указано'};"
                f" срок: {s['term'] or 'не указан'}; стоимость: {s['payment'] or 'не указана'}"
                for i, s in enumerate(pkg["services"], start=1)
            )
            res = pipeline.llm.wizard_summary(pkg["title"], block)
            memo = res.text
            if memo:
                pipeline.cache.put(
                    key, "wizard", f"{req.scenarioId} {signature}", norm,
                    "llm:" + get_settings().llm_model, get_settings().prompt_version,
                    {"answer": memo, "mode": "llm", "model": res.model},
                    tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                    latency_ms=res.latency_ms,
                )
            pkg["memoCached"] = False
    pkg["memo"] = memo
    pkg["llmAvailable"] = pipeline.llm.available
    return pkg


# -------------------------------------------------------------------- кэш
@router.get("/cache/stats")
def cache_stats() -> dict[str, Any]:
    s = get_settings()
    pipeline = get_pipeline()
    return {
        **pipeline.cache.stats(s.price_in, s.price_out),
        "top": pipeline.cache.top_questions(12),
        "recent": pipeline.cache.recent_questions(15),
        "model": s.llm_model,
        "mode": pipeline.llm.mode,
        "ttlDays": s.cache_ttl_days,
    }


@router.post("/cache/clear")
def cache_clear() -> dict[str, Any]:
    return {"removed": get_pipeline().cache.clear()}


# ------------------------------------------------------- качество данных
@router.get("/quality")
def quality() -> dict[str, Any]:
    store = get_store()
    q = store.quality
    services = store.services

    by_completeness: dict[str, int] = {"full": 0, "partial": 0, "poor": 0}
    worst: list[dict[str, Any]] = []
    for svc in services.values():
        c = svc["completeness"]
        if c >= 0.85:
            by_completeness["full"] += 1
        elif c >= 0.5:
            by_completeness["partial"] += 1
        else:
            by_completeness["poor"] += 1
            worst.append({"id": svc["id"], "title": svc["short_title"],
                          "completeness": c, "missing": svc["missing_sections"],
                          "department": svc["department"]})
    worst.sort(key=lambda s: s["completeness"])

    section_fill = []
    total = len(services)
    for sp in SECTIONS:
        if sp.code == "title":
            continue
        empty = q["empty_sections"].get(sp.code, 0)
        section_fill.append({
            "code": sp.code, "label": sp.label,
            "filled": total - empty, "empty": empty,
            "fillRate": round((total - empty) / total, 3) if total else 0,
            "withHtml": q["html_sections"].get(sp.code, 0),
        })

    return {
        "services": total,
        "sections": section_fill,
        "completeness": by_completeness,
        "worst": worst[:25],
        "noLifeSituation": q["no_life_situation"],
        "noBranches": q["no_branches"],
        "missingDepartment": q["missing_department"],
        "unknownDepartmentIds": q["unknown_department_ids"],
        "unknownBranchIds": q["unknown_branch_ids"][:20],
        "unknownBranchCount": len(q["unknown_branch_ids"]),
        "imagesDropped": q["images_dropped"],
        "rawBytes": q["raw_bytes"],
        "cleanBytes": q["clean_bytes"],
        "noiseRemovedPct": round(100 - q["clean_bytes"] / max(1, q["raw_bytes"]) * 100, 1),
    }
