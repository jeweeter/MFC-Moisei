"""Точка входа: FastAPI-приложение «Моисей».

Запуск в разработке:
    uvicorn app.main:app --reload --port 8000   (из каталога backend)
В продакшене отдаёт и API, и собранный фронтенд (frontend/dist).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import get_settings
from .index_store import get_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("moisei")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    log.info("Моисей: загрузка базы знаний…")
    store = get_store()
    st = store.stats()
    log.info(
        "База знаний готова: %s услуг, %s фрагментов, %s ведомств, %s отделений",
        st["services"], st["chunks"], st["departments"], st["branches"],
    )
    log.info(
        "Режим ответов: %s",
        f"LLM ({s.llm_model})" if s.llm_enabled
        else "автономный (extractive) — задайте ANTHROPIC_API_KEY для полного режима",
    )
    yield


app = FastAPI(
    title="Моисей — помощник оператора МФЦ",
    description="Быстрый и достоверный ответ по любой услуге МФЦ на базе RAG.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
