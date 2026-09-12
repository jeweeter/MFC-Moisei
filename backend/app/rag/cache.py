"""Кэш ответов LLM по паре (услуга, вопрос).

Зачем: в окне МФЦ вопросы повторяются («какие документы на загранпаспорт»
спрашивают десятки раз в день во всех отделениях). Каждый такой вопрос —
это 6-10 тыс. входных токенов контекста. Кэш убирает и деньги, и задержку:
повторный ответ отдаётся за единицы миллисекунд вместо 3-8 секунд.

Ключ кэша строится не по сырой строке, а по нормализованному представлению
вопроса (леммы без стоп-слов, упорядоченные), поэтому «какие документы нужны
на загранпаспорт», «документы на загранпаспорт?» и «загранпаспорт какие
документы» дают одно попадание.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..search.normalize import CACHE_FILLER_WORDS, normalize_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    key            TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    service_id     TEXT,
    question       TEXT NOT NULL,
    question_norm  TEXT NOT NULL,
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    payload        TEXT NOT NULL,
    tokens_in      INTEGER DEFAULT 0,
    tokens_out     INTEGER DEFAULT 0,
    latency_ms     INTEGER DEFAULT 0,
    created_at     REAL NOT NULL,
    last_used_at   REAL NOT NULL,
    hits           INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cache_service ON llm_cache(service_id);
CREATE INDEX IF NOT EXISTS idx_cache_used ON llm_cache(last_used_at DESC);

CREATE TABLE IF NOT EXISTS cache_stats (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    hits           INTEGER DEFAULT 0,
    misses         INTEGER DEFAULT 0,
    saved_tokens_in  INTEGER DEFAULT 0,
    saved_tokens_out INTEGER DEFAULT 0,
    saved_ms       INTEGER DEFAULT 0
);
INSERT OR IGNORE INTO cache_stats (id) VALUES (1);

CREATE TABLE IF NOT EXISTS question_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    kind        TEXT,
    service_id  TEXT,
    question    TEXT,
    cached      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_qlog_ts ON question_log(ts DESC);
"""


def normalize_question(question: str) -> str:
    """Нормализация вопроса для ключа кэша: леммы без стоп-слов, отсортированы."""
    lemmas = sorted(set(normalize_text(question)) - CACHE_FILLER_WORDS)
    return " ".join(lemmas) or " ".join(sorted(set(normalize_text(question))))


class AnswerCache:
    def __init__(self, path: Path, ttl_days: int = 30):
        self.path = path
        self.ttl = ttl_days * 86400
        self._local = threading.local()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    @staticmethod
    def make_key(
        kind: str, question: str, model: str, prompt_version: str,
        service_id: str | None = None, extra: str = "",
    ) -> tuple[str, str]:
        norm = normalize_question(question)
        raw = "|".join([kind, service_id or "*", norm, model, prompt_version, extra])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest(), norm

    def get(self, key: str) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM llm_cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if self.ttl and time.time() - row["created_at"] > self.ttl:
            conn.execute("DELETE FROM llm_cache WHERE key = ?", (key,))
            conn.commit()
            return None
        conn.execute(
            "UPDATE llm_cache SET hits = hits + 1, last_used_at = ? WHERE key = ?",
            (time.time(), key),
        )
        conn.execute(
            "UPDATE cache_stats SET hits = hits + 1,"
            " saved_tokens_in = saved_tokens_in + ?,"
            " saved_tokens_out = saved_tokens_out + ?,"
            " saved_ms = saved_ms + ? WHERE id = 1",
            (row["tokens_in"], row["tokens_out"], row["latency_ms"]),
        )
        conn.commit()
        payload = json.loads(row["payload"])
        payload["cached"] = True
        payload["cachedAt"] = row["created_at"]
        payload["cacheHits"] = row["hits"] + 1
        return payload

    def put(
        self, key: str, kind: str, question: str, question_norm: str,
        model: str, prompt_version: str, payload: dict[str, Any],
        service_id: str | None = None, tokens_in: int = 0, tokens_out: int = 0,
        latency_ms: int = 0,
    ) -> None:
        now = time.time()
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (key, kind, service_id, question,"
            " question_norm, model, prompt_version, payload, tokens_in, tokens_out,"
            " latency_ms, created_at, last_used_at, hits)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (key, kind, service_id, question, question_norm, model, prompt_version,
             json.dumps(payload, ensure_ascii=False), tokens_in, tokens_out,
             latency_ms, now, now),
        )
        conn.execute("UPDATE cache_stats SET misses = misses + 1 WHERE id = 1")
        conn.commit()

    def log_question(
        self, kind: str, question: str, service_id: str | None, cached: bool
    ) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO question_log (ts, kind, service_id, question, cached)"
            " VALUES (?,?,?,?,?)",
            (time.time(), kind, service_id, question[:500], int(cached)),
        )
        conn.commit()

    # ------------------------------------------------------------- статистика
    def stats(self, price_in: float, price_out: float) -> dict[str, Any]:
        conn = self._conn()
        st = conn.execute("SELECT * FROM cache_stats WHERE id = 1").fetchone()
        total = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(hits),0) h FROM llm_cache"
        ).fetchone()
        hits, misses = st["hits"], st["misses"]
        requests = hits + misses
        saved_usd = (st["saved_tokens_in"] / 1e6 * price_in
                     + st["saved_tokens_out"] / 1e6 * price_out)
        return {
            "entries": total["c"],
            "hits": hits,
            "misses": misses,
            "hitRate": round(hits / requests, 4) if requests else 0.0,
            "savedTokensIn": st["saved_tokens_in"],
            "savedTokensOut": st["saved_tokens_out"],
            "savedUsd": round(saved_usd, 4),
            "savedSeconds": round(st["saved_ms"] / 1000, 1),
        }

    def top_questions(self, limit: int = 15) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT question, service_id, hits, kind, last_used_at FROM llm_cache"
            " ORDER BY hits DESC, last_used_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_questions(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT ts, kind, service_id, question, cached FROM question_log"
            " ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> int:
        conn = self._conn()
        n = conn.execute("SELECT COUNT(*) c FROM llm_cache").fetchone()["c"]
        conn.execute("DELETE FROM llm_cache")
        conn.execute("UPDATE cache_stats SET hits=0, misses=0, saved_tokens_in=0,"
                     " saved_tokens_out=0, saved_ms=0 WHERE id=1")
        conn.commit()
        return n
