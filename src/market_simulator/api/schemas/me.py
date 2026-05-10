from __future__ import annotations

from pydantic import BaseModel


class MeUserResponse(BaseModel):
    id: str
    email: str | None = None
    display_name: str | None = None
    status: str


class MePlanResponse(BaseModel):
    code: str
    name: str
    monthly_price_usd: float


class MeFeatureFlagsResponse(BaseModel):
    allow_portfolio_runs: bool
    allow_comparison_runs: bool
    allow_parameter_sweeps: bool
    allow_ai_builder: bool
    allow_strategy_history: bool
    allow_rotation_templates: bool
    allow_custom_rotation: bool
    allow_rotation_edit: bool
    allow_advanced_builder: bool


class MeUsageLimitsResponse(BaseModel):
    daily_free_runs: int
    max_saved_strategies: int
    max_tracked_strategies: int
    builder_prompt_daily_limit: int
    builder_prompt_max_chars: int
    max_backtest_years: int
    max_comparison_runs: int


class MeUsageResponse(BaseModel):
    runs_created_today: int
    daily_runs_remaining: int
    saved_strategies: int
    saved_strategies_remaining: int
    tracked_strategies: int
    tracked_strategies_remaining: int
    builder_prompts_used_today: int
    builder_prompts_remaining_today: int


class MeEntitlementsResponse(BaseModel):
    user: MeUserResponse
    plan: MePlanResponse
    features: MeFeatureFlagsResponse
    limits: MeUsageLimitsResponse
    usage: MeUsageResponse
