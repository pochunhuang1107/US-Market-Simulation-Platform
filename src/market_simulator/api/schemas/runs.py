from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, field_serializer, model_validator


class CreateRunRequest(BaseModel):
    strategy_id: str | None = None
    strategy_version_id: str | None = None
    parent_run_id: UUID | None = None
    draft_config: dict[str, Any] | None = None
    run_type: str
    executor_type: str
    request_payload: dict[str, Any]
    max_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_run_source(self):
        has_saved_strategy = self.strategy_id is not None
        has_draft_config = self.draft_config is not None
        has_sweep_base_config = (
            self.run_type == "PARAMETER_SWEEP"
            and isinstance((self.request_payload or {}).get("base_config"), dict)
        )

        if sum([has_saved_strategy, has_draft_config, has_sweep_base_config]) != 1:
            raise ValueError(
                "Exactly one run source is required: strategy_id, draft_config, or parameter sweep base_config"
            )

        if self.strategy_version_id is not None and self.strategy_id is None:
            raise ValueError("strategy_version_id requires strategy_id")

        return self


class SaveDraftRunAsStrategyRequest(BaseModel):
    name: str
    description: str | None = None
    strategy_type: str = "SINGLE_ASSET"


class SaveDraftRunAsStrategyResponse(BaseModel):
    run_id: str
    strategy_id: str
    version_id: str


class PromoteSweepVariantRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    change_note: str | None = None


class PromoteSweepVariantResponse(BaseModel):
    run_id: str
    variant_id: str
    strategy_id: str
    version_id: str
    derived_run_id: str | None = None


class SweepVariantDetailResponse(BaseModel):
    run: "RunResponse"
    variant: dict[str, Any]
    rank: int
    ranking_metric: str | None = None
    sweep_origin: Literal["STANDALONE", "SAVED_STRATEGY"]
    saved_strategy_id: str | None = None
    saved_version_id: str | None = None
    saved_run_id: str | None = None
    chart_data: dict[str, Any] | None = None


class RunListQueryParams(BaseModel):
    status: str | None = None
    executor_type: str | None = None
    run_type: str | None = None
    strategy_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class RunDashboardQueryParams(BaseModel):
    status: list[str] = Field(default_factory=list)
    executor_type: str | None = None
    run_type: str | None = None
    strategy_id: str | None = None
    artifact_storage_type: Literal["LOCAL", "S3"] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: Literal["created_at", "finished_at", "status"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"


class RunExecutionSummary(BaseModel):
    duration_seconds: float | None = None
    attempt_count: int
    max_attempts: int
    progress_pct: int
    progress_message: str | None = None
    is_terminal: bool


class RunProgressResponse(BaseModel):
    run_id: str
    status: str
    progress_pct: int
    progress_message: str | None = None
    heartbeat_at: datetime | None = None
    updated_at: datetime
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
    strategy_name: str | None = None
    strategy_version_number: int | None = None
    source: str | None = None
    source_sweep_run_id: str | None = None
    source_variant_id: str | None = None
    source_variant_rank: int | None = None
    source_ranking_metric: str | None = None

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
    failure_summary: str | None = None

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
        if self.status == "FAILED":
            self.failure_summary = safe_failure_summary(self.error_message)
            self.error_message = self.failure_summary
        else:
            self.failure_summary = None

        if self.started_at and self.finished_at:
            self.duration_seconds = (
                self.finished_at - self.started_at
            ).total_seconds()

        self.artifacts = self.get_artifacts()

        if self.artifacts and artifact_url_resolver is not None:
            self.artifact_download_urls = {}
            for name, uri in self.artifacts.items():
                if not isinstance(uri, str):
                    continue
                download_url = artifact_url_resolver(uri)
                if download_url:
                    self.artifact_download_urls[name] = download_url
        else:
            self.artifact_download_urls = None

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


def safe_failure_summary(error_message: str | None, *, max_length: int = 300) -> str | None:
    if not error_message:
        return None

    normalized = str(error_message).strip()
    classification = None
    if normalized.startswith("[") and "]" in normalized:
        prefix, _, remainder = normalized.partition("]")
        classification = prefix.strip("[]")
        normalized = remainder.strip()

    unsafe_markers = (
        "Traceback",
        'File "',
        "During handling of the above exception",
        "The above exception was the direct cause",
    )
    first_line = normalized.splitlines()[0].strip() if normalized else ""
    if not first_line or any(marker in normalized for marker in unsafe_markers):
        first_line = "Run failed. Check operator logs for details."

    if len(first_line) > max_length:
        first_line = f"{first_line[: max_length - 3].rstrip()}..."

    if classification:
        return f"[{classification}] {first_line}"
    return first_line


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


class TradeEventRuleContext(BaseModel):
    label: str
    summary: str
    actual_label: str | None = None
    actual_value: Any | None = None
    operator: str | None = None
    threshold: Any | None = None
    result: str
    limitation: str | None = None


class TradeCapitalContext(BaseModel):
    trade_notional: float | None = None
    trade_fee: float | None = None
    trade_total_cost: float | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    equity_before_trade: float | None = None
    equity_after_trade: float | None = None
    cash_before_trade: float | None = None
    cash_after_trade: float | None = None
    position_shares_before: int | None = None
    position_shares_after: int | None = None
    position_value_after: float | None = None
    position_allocation_pct_after: float | None = None
    remaining_capacity_after: float | None = None
    max_position_value: float | None = None


class TradeEventContext(BaseModel):
    id: str
    date: str | None = None
    action: str
    side: str
    price: float | None = None
    shares: float | None = None
    event_category: str | None = None
    values_on_date: dict[str, Any] = Field(default_factory=dict)
    rule_context: list[TradeEventRuleContext] = Field(default_factory=list)
    capital_context: TradeCapitalContext | None = None
    rule_summary: str | None = None
    explanation: str


class TradeEventContextResponse(BaseModel):
    total_count: int
    events: list[TradeEventContext]


class RotationSummaryMetrics(BaseModel):
    strategy_return_pct: float | None = None
    market_benchmark_return_pct: float | None = None
    universe_equal_weight_return_pct: float | None = None
    alpha_vs_universe_equal_weight_pct: float | None = None
    max_drawdown_pct: float | None = None
    rebalance_count: int | None = None
    held_assets_count: int | None = None
    universe_size: int | None = None


class RotationAssetRankRow(BaseModel):
    symbol: str
    rank: int | None = None
    trailing_return_pct: float | None = None
    target_weight_pct: float | None = None
    selected: bool = False


class RotationTradeRow(BaseModel):
    action: str
    symbol: str | None = None
    shares: float | None = None
    price: float | None = None
    notional: float | None = None
    fee: float | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None


class RotationHoldingRow(BaseModel):
    symbol: str
    shares: float | None = None
    market_value: float | None = None
    weight_pct: float | None = None


class RotationRebalanceEvent(BaseModel):
    id: str
    date: str
    selected_assets: list[str] = Field(default_factory=list)
    target_weights: dict[str, float] = Field(default_factory=dict)
    asset_ranks: list[RotationAssetRankRow] = Field(default_factory=list)
    trades: list[RotationTradeRow] = Field(default_factory=list)
    cash: float | None = None
    holdings: list[RotationHoldingRow] = Field(default_factory=list)
    risk_filter_passed: bool | None = None
    fallback_used: str | None = None


class RotationReviewResponse(BaseModel):
    is_rotation: bool
    metrics: RotationSummaryMetrics
    total_count: int
    rebalances: list[RotationRebalanceEvent]


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
    result_ref: str | None = None
    result_type: str | None = None
    label: str | None = None
    strategy_id: str | None = None
    strategy_version_id: str | None = None
    strategy_name: str | None = None
    strategy_version_number: int | None = None
    source: str | None = None
    source_sweep_run_id: str | None = None
    source_variant_id: str | None = None
    source_variant_rank: int | None = None
    source_ranking_metric: str | None = None
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


class RunComparisonWindow(BaseModel):
    run_id: str
    result_ref: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class RunComparisonMetadata(BaseModel):
    run_windows: list[RunComparisonWindow]
    overlap_start: str | None = None
    overlap_end: str | None = None
    has_common_overlap: bool
    window_mode: str
    warning_message: str | None = None


class RunComparisonResponse(BaseModel):
    runs: list[RunComparisonSummary]
    metadata: RunComparisonMetadata


class RunComparisonCurvePoint(BaseModel):
    date: str
    value: float


class RunComparisonCurve(BaseModel):
    run_id: str
    result_ref: str | None = None
    label: str | None = None
    benchmark_label: str | None = None
    points: list[RunComparisonCurvePoint]


class RunComparisonChartResponse(BaseModel):
    strategy_curves: list[RunComparisonCurve]
    benchmark_curves: list[RunComparisonCurve]
    strategy_drawdown_curves: list[RunComparisonCurve]
    benchmark_drawdown_curves: list[RunComparisonCurve]
    chart_window_mode: str = "FULL_PERIOD"
    chart_overlap_start: str | None = None
    chart_overlap_end: str | None = None


class RunDashboardResponse(BaseModel):
    run: RunResponse
    chart_data: RunChartDataResponse
    rotation_review: RotationReviewResponse | None = None


class RunDashboardListItem(BaseModel):
    run_id: str
    comparable_result_ref: str | None = None
    result_type: str | None = None
    label: str | None = None
    strategy_id: str | None = None
    strategy_version_id: str | None = None
    strategy_name: str | None = None
    strategy_version_number: int | None = None
    source: str | None = None
    source_sweep_run_id: str | None = None
    source_variant_id: str | None = None
    source_variant_rank: int | None = None
    source_ranking_metric: str | None = None
    status: str
    run_type: str
    executor_type: str
    created_at: datetime
    finished_at: datetime | None = None
    progress_pct: int
    progress_message: str | None = None
    failure_summary: str | None = None
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
    sweep_variant_count: int | None = None
    sweep_variants: list["SweepComparableVariantItem"] = Field(default_factory=list)


class SweepComparableVariantItem(BaseModel):
    comparable_result_ref: str
    sweep_run_id: str
    variant_id: str
    label: str
    rank: int | None = None
    parameters: dict[str, Any] | None = None
    total_return_pct: float | None = None
    benchmark_return_pct: float | None = None
    alpha_vs_benchmark_pct: float | None = None
    cagr_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    trade_count: int | None = None
    status: str | None = None


class RunDashboardListResponse(BaseModel):
    items: list[RunDashboardListItem]
    total: int
    page: int
    page_size: int
    has_next: bool
