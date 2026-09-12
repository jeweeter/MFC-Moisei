"""Схемы запросов API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    serviceId: str | None = None
    useCache: bool = True


class WizardRequest(BaseModel):
    scenarioId: str
    answers: dict[str, list[str]] = Field(default_factory=dict)
    withMemo: bool = True
