"""Единая точка доступа к индексу базы знаний.

Индекс собирается один раз (data/index/index.pkl) и держится в памяти процесса.
Если исходные JSON или словарь синонимов изменились — пересобирается автоматически
при старте, поэтому обновление выгрузки с mfc71.ru не требует ручных действий.
"""
from __future__ import annotations

import functools
import pickle
import threading
from typing import Any

from .config import get_settings
from .ingest.build_index import build, index_is_fresh
from .ingest.schema import RECIPIENT_LABELS, SECTIONS
from .search.hybrid import HybridSearcher
from .search.normalize import SynonymIndex

_lock = threading.Lock()


class IndexStore:
    def __init__(self) -> None:
        s = get_settings()
        if not index_is_fresh():
            build(verbose=True)
        with (s.index_dir / "index.pkl").open("rb") as f:
            self.index: dict[str, Any] = pickle.load(f)
        self.synonyms = SynonymIndex.load(s.dict_dir / "synonyms.json")
        self.searcher = HybridSearcher(self.index, self.synonyms)

    # ------------------------------------------------------------ справочники
    @property
    def services(self) -> dict[str, dict]:
        return self.index["services"]

    @property
    def quality(self) -> dict[str, Any]:
        return self.index["quality"]

    def classification(self, kind: str) -> dict[str, dict]:
        return self.index["classification"].get(kind, {})

    @functools.cached_property
    def departments(self) -> list[dict]:
        counts: dict[str, int] = {}
        for svc in self.services.values():
            if svc["department_id"]:
                counts[svc["department_id"]] = counts.get(svc["department_id"], 0) + 1
        out = [
            {"id": cid, "name": c.get("name") or cid, "count": counts.get(cid, 0)}
            for cid, c in self.classification("by_department").items()
        ]
        out = [d for d in out if d["count"]]
        out.sort(key=lambda d: -d["count"])
        return out

    @functools.cached_property
    def life_situations(self) -> list[dict]:
        counts: dict[str, int] = {}
        for svc in self.services.values():
            for lid in svc["life_situation_ids"]:
                counts[lid] = counts.get(lid, 0) + 1
        out = [
            {"id": cid, "name": c.get("name") or cid, "count": counts.get(cid, 0)}
            for cid, c in self.classification("by_life_situation").items()
        ]
        out.sort(key=lambda d: -d["count"])
        return out

    @functools.cached_property
    def branches(self) -> list[dict]:
        counts: dict[str, int] = {}
        for svc in self.services.values():
            for bid in svc["branch_ids"]:
                counts[bid] = counts.get(bid, 0) + 1
        out = []
        for cid, c in self.classification("by_branch").items():
            out.append({
                "id": cid,
                "name": c.get("name") or cid,
                "address": c.get("address"),
                "schedule": c.get("schedule") or [],
                "windowCount": c.get("windowCount"),
                "chief": c.get("chiefName"),
                "code": c.get("code"),
                "count": counts.get(cid, 0),
            })
        out.sort(key=lambda d: (d["name"] or ""))
        return out

    @functools.cached_property
    def recipients(self) -> list[dict]:
        counts: dict[str, int] = {}
        for svc in self.services.values():
            for rid in svc["recipient_ids"]:
                counts[rid] = counts.get(rid, 0) + 1
        return [
            {"id": rid, "name": RECIPIENT_LABELS.get(rid, rid), "count": counts.get(rid, 0)}
            for rid in RECIPIENT_LABELS
        ]

    # -------------------------------------------------------------- утилиты
    @property
    def variant_groups(self) -> dict[str, list[str]]:
        return self.index.get("variant_groups", {})

    def variants_of(self, service_id: str) -> list[dict]:
        """Муниципальные «двойники» услуги: та же услуга в других МО."""
        svc = self.services.get(service_id)
        if not svc or not svc.get("variant_group"):
            return []
        out = []
        for sid in self.variant_groups.get(svc["variant_group"], []):
            other = self.services[sid]
            out.append({
                "id": sid,
                "label": other.get("variant_label") or other["short_title"],
                "department": other["department"],
                "current": sid == service_id,
            })
        out.sort(key=lambda v: (not v["current"], v["label"]))
        return out

    def service(self, service_id: str) -> dict | None:
        return self.services.get(service_id)

    def branch(self, branch_id: str) -> dict | None:
        return self.classification("by_branch").get(branch_id)

    def chunk_by_id(self, chunk_id: str) -> dict | None:
        for ch in self.index["chunks"]:
            if ch["chunkId"] == chunk_id:
                return ch
        return None

    def section_labels(self) -> dict[str, str]:
        return {s.code: s.label for s in SECTIONS}

    def stats(self) -> dict[str, Any]:
        q = self.quality
        return {
            "services": len(self.services),
            "chunks": len(self.index["chunks"]),
            "departments": len(self.departments),
            "branches": len([b for b in self.branches if b["count"]]),
            "lifeSituations": len(self.life_situations),
            "vocabulary": len(self.index["bm25"]["vocabulary"]),
            "builtAt": self.index["built_at"],
            "buildSeconds": self.index["build_seconds"],
            "rawBytes": q["raw_bytes"],
            "cleanBytes": q["clean_bytes"],
            "noiseRemovedPct": round(100 - q["clean_bytes"] / max(1, q["raw_bytes"]) * 100, 1),
        }


_store: IndexStore | None = None


def get_store() -> IndexStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = IndexStore()
    return _store


def reset_store() -> None:
    global _store
    with _lock:
        _store = None
