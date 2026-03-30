from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

class PositionSizingV1(BaseModel):
    type: Literal["percent_of_equity"] = "percent_of_equity"
    value: float = Field(gt=0, le=1.0)

class EntryExitRuleV1(BaseModel):
    type: Literal["rsi_below", "rsi_above"]
    lookback: int = Field(gt=0)
    threshold: float = Field(ge=0, le=100)

class RiskV1(BaseModel):
    stop_loss_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    take_profit_pct: Optional[float] = Field(default=None, gt=0, lt=10)

class StrategyV1(BaseModel):
    name: str
    symbol: str
    benchmark: str
    start_date: date
    end_date: date
    initial_capital: float = Field(gt=0)
    transaction_cost_bps: float = Field(ge=0)
    position_sizing: PositionSizingV1
    entry: EntryExitRuleV1
    exit: EntryExitRuleV1
    risk: RiskV1 = RiskV1()
