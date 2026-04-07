from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, field_serializer


class CreateRunRequest(BaseModel):
    strategy_id: str
    strategy_version_id: str | None = None
    run_type: str
    executor_type: str
    request_payload: dict[str, Any]
    max_attempts: int = Field(default=3, ge=1, le=10)


class RunListQueryParams(BaseModel):
    status: str | None = None
    executor_type: str | None = None
    run_type: str | None = None
    strategy_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class RunExecutionSummary(BaseModel):
    duration_seconds: float | None = None
    attempt_count: int
    max_attempts: int
    progress_pct: int
    progress_message: str | None = None
    is_terminal: bool


class RunArtifactSummary(BaseModel):
    artifact_dir: str | None = None
    artifact_root_uri: str | None = None
    artifact_storage_type: str
    manifest: dict[str, Any] | None = None
    download_urls: dict[str, str] | None = None


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    strategy_id: UUID | None
    strategy_version_id: UUID | None

    run_type: str
    executor_type: str
    status: str

    request_payload: dict[str, Any]
    summary_json: dict[str, Any] | None
    artifact_manifest_json: dict[str, Any] | None

    artifact_dir: str | None
    artifact_storage_type: str
    artifact_root_uri: str | None

    error_message: str | None

    is_daily_tracking_run: bool
    parent_run_id: UUID | None

    queued_at: datetime | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    leased_until: datetime | None
    finished_at: datetime | None

    attempt_count: int
    max_attempts: int
    worker_id: str | None
    progress_pct: int
    progress_message: str | None

    duration_seconds: float | None = None
    artifacts: dict[str, Any] | None = None
    artifact_download_urls: dict[str, str] | None = None
    is_terminal: bool | None = None

    execution: RunExecutionSummary | None = None
    artifact_summary: RunArtifactSummary | None = None

    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "id",
        "user_id",
        "strategy_id",
        "strategy_version_id",
        "parent_run_id",
    )
    def serialize_uuid(self, value: UUID | None):
        return str(value) if value is not None else None

    def get_artifacts(self) -> dict[str, Any] | None:
        if not self.artifact_manifest_json:
            return None
        return self.artifact_manifest_json

    def enrich(
        self,
        artifact_url_resolver: callable | None = None,
    ) -> "RunResponse":
        if self.started_at and self.finished_at:
            self.duration_seconds = (
                self.finished_at - self.started_at
            ).total_seconds()

        self.artifacts = self.get_artifacts()

        if self.artifacts and artifact_url_resolver is not None:
            self.artifact_download_urls = {
                name: artifact_url_resolver(uri)
                for name, uri in self.artifacts.items()
            }
        else:
            self.artifact_download_urls = self.artifacts

        self.is_terminal = self.status in {
            "SUCCEEDED",
            "FAILED",
            "CANCELED",
        }

        self.execution = RunExecutionSummary(
            duration_seconds=self.duration_seconds,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            progress_pct=self.progress_pct,
            progress_message=self.progress_message,
            is_terminal=bool(self.is_terminal),
        )

        self.artifact_summary = RunArtifactSummary(
            artifact_dir=self.artifact_dir,
            artifact_root_uri=self.artifact_root_uri,
            artifact_storage_type=self.artifact_storage_type,
            manifest=self.artifacts,
            download_urls=self.artifact_download_urls,
        )

        return self


class RunListResponse(BaseModel):
    items: list[RunResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


class RunActionResponse(BaseModel):
    run_id: str
    status: str
    message: str


class RecoverStaleRunsResponse(BaseModel):
    recovered_count: int
    run_ids: list[str]


class EquityCurvePoint(BaseModel):
    date: str
    strategy_equity: float
    benchmark_equity: float | None = None


class DrawdownCurvePoint(BaseModel):
    date: str
    strategy_drawdown_pct: float
    benchmark_drawdown_pct: float | None = None


class MonthlyReturnPoint(BaseModel):
    month: str
    return_pct: float


class SleeveEquityPoint(BaseModel):
    date: str
    core_equity: float | None = None
    overlay_equity: float | None = None


class SleeveWeightPoint(BaseModel):
    date: str
    core_weight_pct: float | None = None
    overlay_weight_pct: float | None = None


class TradeMarkerPoint(BaseModel):
    date: str
    side: str
    shares: float | None = None
    price: float | None = None
    reason: str | None = None


class RunChartDataResponse(BaseModel):
    run_id: str
    equity_curve: list[EquityCurvePoint]
    drawdown_curve: list[DrawdownCurvePoint]
    monthly_returns: list[MonthlyReturnPoint]
    sleeve_equity_curve: list[SleeveEquityPoint]
    sleeve_weight_curve: list[SleeveWeightPoint]
    trade_markers: list[TradeMarkerPoint]


class RunComparisonSummary(BaseModel):
    run_id: str
    strategy_id: str | None = None
    strategy_version_id: str | None = None
    status: str
    total_return_pct: float | None = None
    benchmark_return_pct: float | None = None
    alpha_vs_benchmark_pct: float | None = None
    cagr_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    benchmark_max_drawdown_pct: float | None = None
    trade_count: int | None = None
    win_rate_pct: float | None = None


class RunComparisonMonthlyPoint(BaseModel):
    month: str
    values: dict[str, float | None]


class RunComparisonResponse(BaseModel):
    runs: list[RunComparisonSummary]
    monthly_returns: list[RunComparisonMonthlyPoint]


class RunComparisonCurvePoint(BaseModel):
    date: str
    equity: float


class RunComparisonCurve(BaseModel):
    run_id: str
    points: list[RunComparisonCurvePoint]


class RunComparisonChartResponse(BaseModel):
    curves: list[RunComparisonCurve]


class RunDashboardResponse(BaseModel):
    run: RunResponse
    chart_data: RunChartDataResponse


class RunDashboardListItem(BaseModel):
    run_id: str
    strategy_id: str | None = None
    strategy_version_id: str | None = None
    status: str
    run_type: str
    executor_type: str
    created_at: datetime
    finished_at: datetime | None = None
    progress_pct: int
    progress_message: str | None = None
    artifact_storage_type: str
    has_artifacts: bool
    total_return_pct: float | None = None
    benchmark_return_pct: float | None = None
    alpha_vs_benchmark_pct: float | None = None
    cagr_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    trade_count: int | None = None
    win_rate_pct: float | None = None


class RunDashboardListResponse(BaseModel):
    items: list[RunDashboardListItem]
    total: int
    page: int
    page_size: int
    has_next: bool