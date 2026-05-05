from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PositionState:
    shares: int = 0
    avg_entry_price: float = 0.0
    partial_take_profit_count: int = 0
    scale_steps: int = 0

    @property
    def in_position(self) -> bool:
        return self.shares > 0


@dataclass
class PortfolioState:
    # separate sleeve cash buckets
    core_cash: float
    overlay_cash: float

    # sleeve starting capital
    core_initial_capital: float = 0.0
    overlay_initial_capital: float = 0.0

    # overlay sleeve state
    overlay_realized_pnl: float = 0.0
    overlay_fees_paid: float = 0.0
    position: PositionState = field(default_factory=PositionState)
    last_exit_bar_index: int | None = None
    last_scale_in_bar_index: int | None = None

    # core sleeve state
    core_shares: int = 0
    core_entry_price: float = 0.0
    core_fees_paid: float = 0.0

    @property
    def cash(self) -> float:
        return self.core_cash + self.overlay_cash

    def core_market_value(self, close: float) -> float:
        return self.core_shares * close

    def overlay_market_value(self, close: float) -> float:
        return self.position.shares * close

    def core_equity(self, close: float) -> float:
        return self.core_cash + self.core_market_value(close)

    def overlay_equity(self, close: float) -> float:
        return self.overlay_cash + self.overlay_market_value(close)

    def total_equity(self, close: float) -> float:
        return self.core_equity(close) + self.overlay_equity(close)
