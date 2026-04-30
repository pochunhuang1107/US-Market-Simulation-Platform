from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from market_simulator.api.schemas.runs import RunDashboardListItem


class CreateStrategyRequest(BaseModel):
    name: str
    description: Optional[str]
    strategy_type: str
    config: Dict


class CreateStrategyVersionRequest(BaseModel):
    config: Dict
    change_note: Optional[str] = None


class StrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    description: str | None = None
    strategy_type: str
    visibility: str
    status: str
    current_version_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "user_id", "current_version_id")
    def serialize_uuid(self, value: UUID | None):
        return str(value) if value is not None else None


class StrategyReferencePerformance(BaseModel):
    run_id: str
    source: str | None = None
    source_sweep_run_id: str | None = None
    source_variant_id: str | None = None
    source_variant_rank: int | None = None
    source_ranking_metric: str | None = None
    finished_at: datetime | None = None
    total_return_pct: float | None = None
    benchmark_return_pct: float | None = None
    alpha_vs_benchmark_pct: float | None = None
    cagr_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    benchmark_max_drawdown_pct: float | None = None
    trade_count: int | None = None
    win_rate_pct: float | None = None


StrategyLatestPerformance = StrategyReferencePerformance


class StrategyVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    strategy_id: UUID
    version_number: int
    config_json: dict
    config_hash: str
    change_note: str | None = None
    reference_run_id: UUID | None = None
    reference_performance: StrategyReferencePerformance | None = None
    created_by_user_id: UUID
    created_at: datetime
    is_current: bool = False

    @field_serializer("id", "strategy_id", "reference_run_id", "created_by_user_id")
    def serialize_uuid(self, value: UUID | None):
        return str(value) if value is not None else None


class StrategyDashboardResponse(BaseModel):
    strategy: StrategyResponse
    versions: list[StrategyVersionSummary]
    associated_runs: list[RunDashboardListItem]
    total_runs: int
    reference_run_id: str | None = None
    reference_finished_at: datetime | None = None
    reference_performance: StrategyReferencePerformance | None = None
    latest_run_id: str | None = None
    latest_finished_at: datetime | None = None
    latest_performance: StrategyLatestPerformance | None = None
