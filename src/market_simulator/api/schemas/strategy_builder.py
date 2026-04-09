from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StrategyBuilderContext(BaseModel):
    strategy_id: str | None = None
    base_version_id: str | None = None
    mode: str | None = Field(default=None, description="Optional UI hint such as NEW_STRATEGY or NEW_VERSION")
    current_config: dict[str, Any] | None = None


class StrategyBuilderGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    context: StrategyBuilderContext | None = None


class StrategyBuilderGenerateResponse(BaseModel):
    config: dict[str, Any]
    summary: str
    warnings: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)