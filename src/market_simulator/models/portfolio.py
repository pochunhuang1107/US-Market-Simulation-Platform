from __future__ import annotations

from typing import List
from pydantic import BaseModel


class StrategyAllocation(BaseModel):
    name: str
    weight: float
    strategy_path: str


class PortfolioConfig(BaseModel):
    name: str
    start_date: str
    end_date: str
    initial_capital: float
    strategies: List[StrategyAllocation]