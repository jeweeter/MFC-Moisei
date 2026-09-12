"""Оценка качества поиска: Recall@k и MRR на наборе реальных формулировок.

Запуск: python -m tests.eval_search  (из каталога backend)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index_store import get_store  # noqa: E402

K_VALUES = (1, 3, 5, 10)


def main() -> int:
    cases = json.loads(
        (Path(__file__).parent / "eval_queries.json").read_text(encoding="utf-8")
    )["cases"]
    store = get_store()
    searcher = store.searcher

    hits_at = {k: 0 for k in K_VALUES}
    rr_total = 0.0
    latencies: list[float] = []
    failures: list[tuple[str, list[str]]] = []

    for case in cases:
        q, pattern = case["q"], re.compile(case["expect"], re.IGNORECASE)
        t0 = time.perf_counter()
        results, _ = searcher.search_services(q, limit=10)
        latencies.append((time.perf_counter() - t0) * 1000)

        rank = None
        titles: list[str] = []
        for i, hit in enumerate(results):
            title = store.services[hit.service_id]["title"]
            titles.append(title)
            if rank is None and pattern.search(title):
                rank = i + 1
        if rank:
            rr_total += 1.0 / rank
            for k in K_VALUES:
                if rank <= k:
                    hits_at[k] += 1
        else:
            failures.append((q, [t[:70] for t in titles[:3]]))

    n = len(cases)
    print(f"Запросов: {n}")
    for k in K_VALUES:
        print(f"  Recall@{k:<2} = {hits_at[k] / n:.1%}  ({hits_at[k]}/{n})")
    print(f"  MRR      = {rr_total / n:.3f}")
    lat = sorted(latencies)
    print(f"  Латентность: median {lat[len(lat) // 2]:.0f} мс, p95 {lat[int(len(lat) * 0.95)]:.0f} мс")
    if failures:
        print(f"\nНе найдено в топ-10 ({len(failures)}):")
        for q, tops in failures:
            print(f"  ✗ {q}")
            for t in tops:
                print(f"      → {t}")
    return 0 if hits_at[5] / n >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
