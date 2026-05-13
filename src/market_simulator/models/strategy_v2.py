from __future__ import annotations

from datetime import date
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class AllocationSpec(BaseModel):
    entry_mode: Literal["percent_of_equity"] = "percent_of_equity"
    entry_value: float = Field(gt=0, le=1.0)
    max_position_pct: float = Field(default=1.0, gt=0, le=1.0)


class PartialTakeProfitSpec(BaseModel):
    trigger_profit_pct: float = Field(gt=0)
    sell_fraction_of_position: float = Field(gt=0, le=1.0)
    max_triggers: int = Field(default=1, ge=1, le=20)


class RiskSpec(BaseModel):
    stop_loss_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    take_profit_pct: Optional[float] = Field(default=None, gt=0)
    partial_take_profit: Optional[PartialTakeProfitSpec] = None
    cooldown_bars: int = Field(default=0, ge=0, le=252)


class CoreOverlaySpec(BaseModel):
    enabled: bool = False
    core_allocation_pct: float = Field(default=0.0, ge=0.0, le=1.0)


class PositionManagementSpec(BaseModel):
    scale_in_fraction: float = Field(default=0.25, gt=0.0, le=1.0)
    scale_out_fraction: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    exit_behavior: Literal["scale_out", "sell_all"] = "scale_out"
    profit_reduce_threshold: Optional[float] = Field(default=None, gt=0.0, lt=1.0)
    max_scale_in_steps: Optional[int] = Field(default=None, gt=0)
    min_bars_between_scale_ins: int = Field(default=0, ge=0)
    scale_in_requires_persistent_signal: bool = False
    minimum_trade_notional: Optional[float] = Field(default=None, gt=0.0)
    minimum_trade_pct_of_equity: Optional[float] = Field(default=None, gt=0.0, lt=1.0)
    minimum_trade_shares: Optional[int] = Field(default=None, gt=0)


class AtomicRule(BaseModel):
    kind: Literal["atomic"] = "atomic"
    type: Literal[
        "rsi_below",
        "rsi_above",
        "sma_cross_above",
        "sma_cross_below",
        "sma_above",
        "macd_bullish_cross",
        "macd_bearish_cross",
        "kd_golden_cross",
        "kd_dead_cross",
        "month_in",
        "relative_return_above",
        "series_below",
        "series_above",
        "realized_volatility_below",
        "realized_volatility_above",
        "bullish_candle",
        "bearish_candle",
        "close_above_previous_high",
        "close_below_previous_low",
        "close_near_high",
        "close_near_low",
    ]
    symbol: Optional[str] = None
    lookback: Optional[int] = None
    threshold: Optional[float] = None
    fast_window: Optional[int] = None
    slow_window: Optional[int] = None
    month_values: Optional[list[int]] = None
    reference_symbol: Optional[str] = None

    @model_validator(mode="after")
    def validate_fields(self) -> "AtomicRule":
        if self.type in {
            "rsi_below",
            "rsi_above",
            "relative_return_above",
            "realized_volatility_below",
            "realized_volatility_above",
        } and self.lookback is None:
            raise ValueError("lookback required")
        if self.type in {
            "rsi_below",
            "rsi_above",
            "relative_return_above",
            "series_below",
            "series_above",
            "realized_volatility_below",
            "realized_volatility_above",
        } and self.threshold is None:
            raise ValueError("threshold required")
        if self.type in {"series_below", "series_above"} and not self.symbol:
            raise ValueError("symbol required")
        if self.type in {"sma_cross_above", "sma_cross_below", "sma_above"} and (
            self.fast_window is None or self.slow_window is None
        ):
            raise ValueError("windows required")
        if self.type == "month_in" and not self.month_values:
            raise ValueError("month_values required")
        if self.type == "relative_return_above" and not self.reference_symbol:
            raise ValueError("reference_symbol required")
        return self


class NotRule(BaseModel):
    kind: Literal["not"] = "not"
    rule: "RuleNode"


class GroupRule(BaseModel):
    kind: Literal["group"] = "group"
    operator: Literal["AND", "OR"]
    rules: list["RuleNode"]


class WindowRule(BaseModel):
    kind: Literal["window"] = "window"
    window_bars: int = Field(gt=0, le=252)
    mode: Literal["ANY", "ALL"] = "ANY"
    rule: "RuleNode"


class SequenceRule(BaseModel):
    kind: Literal["sequence"] = "sequence"
    window_bars: int = Field(gt=1, le=252)
    steps: list["RuleNode"] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_steps(self) -> "SequenceRule":
        if len(self.steps) < 2:
            raise ValueError("sequence requires at least 2 steps")
        return self


RuleNode = Union[AtomicRule, NotRule, GroupRule, WindowRule, SequenceRule]


class RotationRankingSpec(BaseModel):
    type: Literal["relative_return"] = "relative_return"
    lookback: int = Field(gt=0, le=756)
    descending: bool = True


class RotationRebalanceSpec(BaseModel):
    frequency: Literal["monthly", "weekly", "quarterly"] = "monthly"
    day: Literal["first_trading_day"] = "first_trading_day"


class RotationSelectionSpec(BaseModel):
    top_n: int = Field(ge=1, le=50)


class RotationAllocationSpec(BaseModel):
    weighting: Literal["equal_weight"] = "equal_weight"
    max_position_pct: float = Field(default=1.0, gt=0, le=1.0)


class RotationFallbackSpec(BaseModel):
    type: Literal["cash", "asset"] = "cash"
    symbol: Optional[str] = None

    @model_validator(mode="after")
    def validate_symbol(self) -> "RotationFallbackSpec":
        if self.type == "asset" and not self.symbol:
            raise ValueError("symbol required for asset fallback")
        return self


class ModelSignalFallbackSpec(BaseModel):
    type: Literal["cash", "asset"] = "cash"
    symbol: Optional[str] = None

    @model_validator(mode="after")
    def validate_symbol(self) -> "ModelSignalFallbackSpec":
        if self.type == "asset" and not self.symbol:
            raise ValueError("symbol required for asset fallback")
        if self.symbol:
            self.symbol = self.symbol.upper()
        return self


class ModelSignalRebalanceSpec(BaseModel):
    frequency: Literal["monthly", "weekly", "quarterly"] = "monthly"
    day: Literal["first_trading_day"] = "first_trading_day"


class ModelSignalSpec(BaseModel):
    enabled: bool = False
    model_version: str = ""
    ranking_field: str = "score"
    universe: list[str] = Field(default_factory=list)
    top_n: Optional[int] = Field(default=None, ge=1, le=50)
    rebalance: ModelSignalRebalanceSpec = ModelSignalRebalanceSpec()
    fallback: ModelSignalFallbackSpec = ModelSignalFallbackSpec()
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    signal_bucket_filter: Optional[list[str]] = None

    @field_validator("signal_bucket_filter", mode="before")
    @classmethod
    def normalize_signal_bucket_filter(cls, value):
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def validate_model_signal(self) -> "ModelSignalSpec":
        self.model_version = self.model_version.strip()
        self.ranking_field = self.ranking_field.strip()
        self.universe = [symbol.upper() for symbol in self.universe]
        if self.signal_bucket_filter is not None:
            self.signal_bucket_filter = [
                bucket.strip()
                for bucket in self.signal_bucket_filter
                if bucket and bucket.strip()
            ]

        if self.enabled:
            if not self.model_version:
                raise ValueError("model_version required when model_signal is enabled")
            if not self.ranking_field:
                raise ValueError("ranking_field required when model_signal is enabled")
            if not self.universe:
                raise ValueError("universe required when model_signal is enabled")
            if self.top_n is None:
                raise ValueError("top_n required when model_signal is enabled")
            if self.top_n > len(self.universe):
                raise ValueError("top_n cannot exceed universe size")

            from market_simulator.settings import get_settings

            supported_symbols = set(get_settings().supported_etf_symbols)
            symbols = set(self.universe)
            if self.fallback.type == "asset" and self.fallback.symbol:
                symbols.add(self.fallback.symbol)
            unsupported = sorted(symbols - supported_symbols)
            if unsupported:
                raise ValueError(
                    "model_signal contains unsupported ETF symbols: "
                    f"{', '.join(unsupported)}"
                )

        return self


class RotationSpec(BaseModel):
    enabled: bool = False
    universe: list[str] = Field(default_factory=list)
    ranking: Optional[RotationRankingSpec] = None
    rebalance: RotationRebalanceSpec = RotationRebalanceSpec()
    selection: Optional[RotationSelectionSpec] = None
    allocation: RotationAllocationSpec = RotationAllocationSpec()
    risk_filter: Optional[RuleNode] = None
    fallback: RotationFallbackSpec = RotationFallbackSpec()

    @model_validator(mode="after")
    def validate_rotation(self) -> "RotationSpec":
        self.universe = [symbol.upper() for symbol in self.universe]
        if self.enabled:
            if not self.universe:
                raise ValueError("universe required when rotation is enabled")
            if self.ranking is None:
                raise ValueError("ranking required when rotation is enabled")
            if self.selection is None:
                raise ValueError("selection required when rotation is enabled")
            if self.selection.top_n > len(self.universe):
                raise ValueError("selection.top_n cannot exceed universe size")
        if self.fallback.symbol:
            self.fallback.symbol = self.fallback.symbol.upper()
        return self


class StrategyV2(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    name: str
    tradable_symbol: str
    benchmark_symbol: str
    reference_symbols: list[str] = []
    start_date: date
    end_date: date
    initial_capital: float = Field(gt=0)
    transaction_cost_bps: float = Field(ge=0)
    allocation: Optional[AllocationSpec] = None
    entry_rule: Optional[RuleNode] = None
    exit_rule: Optional[RuleNode] = None
    risk: RiskSpec = RiskSpec()
    core_overlay: CoreOverlaySpec = CoreOverlaySpec()
    position_management: Optional[PositionManagementSpec] = None
    rotation: Optional[RotationSpec] = None
    model_signal: Optional[ModelSignalSpec] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "StrategyV2":
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be earlier than end_date")
        rotation_enabled = bool(self.rotation and self.rotation.enabled)
        model_signal_enabled = bool(self.model_signal and self.model_signal.enabled)
        if rotation_enabled and model_signal_enabled:
            raise ValueError("rotation and model_signal cannot both be enabled")
        if not rotation_enabled and not model_signal_enabled:
            if self.allocation is None:
                raise ValueError("allocation required unless rotation or model_signal is enabled")
            if self.entry_rule is None:
                raise ValueError("entry_rule required unless rotation or model_signal is enabled")
            if self.exit_rule is None:
                raise ValueError("exit_rule required unless rotation or model_signal is enabled")
        return self

    def rotation_required_reference_symbols(self) -> list[str]:
        if not self.rotation or not self.rotation.enabled:
            return []

        symbols = set(self.reference_symbols)
        symbols.update(self.rotation.universe)
        if self.rotation.fallback.type == "asset" and self.rotation.fallback.symbol:
            symbols.add(self.rotation.fallback.symbol)
        symbols.add(self.benchmark_symbol)
        symbols.discard(self.tradable_symbol)
        return sorted(symbols)

    def model_signal_required_reference_symbols(self) -> list[str]:
        if not self.model_signal or not self.model_signal.enabled:
            return []

        symbols = set(self.reference_symbols)
        symbols.update(self.model_signal.universe)
        if self.model_signal.fallback.type == "asset" and self.model_signal.fallback.symbol:
            symbols.add(self.model_signal.fallback.symbol)
        symbols.add(self.benchmark_symbol)
        symbols.discard(self.tradable_symbol)
        return sorted(symbols)


NotRule.model_rebuild()
GroupRule.model_rebuild()
WindowRule.model_rebuild()
SequenceRule.model_rebuild()
RotationSpec.model_rebuild()
ModelSignalSpec.model_rebuild()
