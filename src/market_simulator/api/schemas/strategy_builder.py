from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StrategyBuilderContext(BaseModel):
    strategy_id: str | None = None
    base_version_id: str | None = None
    mode: str | None = Field(
        default=None,
        description="Optional UI hint such as NEW_STRATEGY or NEW_VERSION",
    )
    current_config: dict[str, Any] | None = None


class StrategyBuilderGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    context: StrategyBuilderContext | None = None


class StrategyBuilderResponseType(str, Enum):
    ANSWER = "ANSWER"
    CREATE_DRAFT = "CREATE_DRAFT"
    UPDATE_DRAFT = "UPDATE_DRAFT"
    PARAMETER_SWEEP_DRAFT = "PARAMETER_SWEEP_DRAFT"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class StrategyBuilderAnswerType(str, Enum):
    SUPPORTED_SYMBOLS = "SUPPORTED_SYMBOLS"
    DATA_COVERAGE = "DATA_COVERAGE"
    PLAN_LIMITS = "PLAN_LIMITS"
    SUPPORTED_STRATEGY_TYPES = "SUPPORTED_STRATEGY_TYPES"
    GENERAL = "GENERAL"


class StrategyBuilderValidationType(str, Enum):
    UNSUPPORTED_SYMBOL = "UNSUPPORTED_SYMBOL"
    DATA_COVERAGE = "DATA_COVERAGE"
    PLAN_LIMIT = "PLAN_LIMIT"
    INVALID_DATE_FORMAT = "INVALID_DATE_FORMAT"
    UNSUPPORTED_EDIT = "UNSUPPORTED_EDIT"
    GENERAL = "GENERAL"


class StrategyBuilderGuidanceType(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    UNSUPPORTED_EDIT_TARGET = "UNSUPPORTED_EDIT_TARGET"
    GENERAL_GUIDANCE = "GENERAL_GUIDANCE"


class StrategyBuilderAnswerData(BaseModel):
    answer_type: StrategyBuilderAnswerType
    supported_symbols: list[str] = Field(default_factory=list)
    supported_data_start: str | None = None
    supported_data_end: str | None = None
    max_backtest_years: int | None = None


class StrategyBuilderValidationData(BaseModel):
    validation_type: StrategyBuilderValidationType
    unsupported_symbols: list[str] = Field(default_factory=list)
    supported_data_start: str | None = None
    supported_data_end: str | None = None
    max_backtest_years: int | None = None
    suggested_action: str | None = None


class StrategyBuilderGuidanceData(BaseModel):
    guidance_type: StrategyBuilderGuidanceType
    suggested_actions: list[str] = Field(default_factory=list)


class StrategyBuilderParameterSweepDraftData(BaseModel):
    title: str
    base_config: dict[str, Any]
    grid: dict[str, list[Any]]
    ranking_metric: str
    variant_count: int
    max_variants: int
    summary: str


class StrategyBuilderGenerateResponse(BaseModel):
    response_type: StrategyBuilderResponseType
    message: str
    config: dict[str, Any] | None = None
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    answer_data: StrategyBuilderAnswerData | None = None
    validation_data: StrategyBuilderValidationData | None = None
    guidance_data: StrategyBuilderGuidanceData | None = None
    sweep_draft: StrategyBuilderParameterSweepDraftData | None = None
    translation_provider: str = "deterministic"
    translation_mode: str = "deterministic"
    llm_enabled: bool = False
