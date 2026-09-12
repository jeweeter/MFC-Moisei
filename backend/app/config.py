"""Конфигурация приложения «Моисей»."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

load_dotenv(ROOT_DIR / ".env")


class Settings:
    """Настройки читаются из переменных окружения (.env в корне проекта)."""

    # --- Пути ---
    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    raw_dir: Path = ROOT_DIR / "data" / "raw"
    index_dir: Path = ROOT_DIR / "data" / "index"
    dict_dir: Path = ROOT_DIR / "data" / "dictionaries"

    knowledge_file: Path = ROOT_DIR / "data" / "raw" / "db_knowledge.json"
    classification_file: Path = ROOT_DIR / "data" / "raw" / "flat_classification.json"
    index_file: Path = ROOT_DIR / "data" / "index" / "index.json.gz"
    cache_db: Path = ROOT_DIR / "data" / "index" / "cache.sqlite3"

    # --- LLM ---
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    llm_model: str = os.getenv("MOISEI_LLM_MODEL", "claude-sonnet-5")
    llm_max_tokens: int = int(os.getenv("MOISEI_LLM_MAX_TOKENS", "1600"))
    # Цена за 1M токенов (для подсчёта экономии на кэше), USD
    price_in: float = float(os.getenv("MOISEI_PRICE_IN", "3.0"))
    price_out: float = float(os.getenv("MOISEI_PRICE_OUT", "15.0"))

    # --- Поиск ---
    top_k_chunks: int = int(os.getenv("MOISEI_TOP_K", "12"))
    cache_ttl_days: int = int(os.getenv("MOISEI_CACHE_TTL_DAYS", "30"))

    # Версия промпта: меняется -> кэш инвалидируется
    prompt_version: str = "v3"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
