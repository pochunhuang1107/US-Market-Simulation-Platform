from __future__ import annotations

from datetime import date
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


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
    allocation: AllocationSpec
    entry_rule: RuleNode
    exit_rule: RuleNode
    risk: RiskSpec = RiskSpec()
    core_overlay: CoreOverlaySpec = CoreOverlaySpec()
    position_management: Optional[PositionManagementSpec] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "StrategyV2":
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be earlier than end_date")
        return self


NotRule.model_rebuild()
GroupRule.model_rebuild()
WindowRule.model_rebuild()
SequenceRule.model_rebuild()
