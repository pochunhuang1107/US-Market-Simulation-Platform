from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine.runner import run_simulation
from market_simulator.models.strategy_v2 import StrategyV2


def _market_df(symbol: str, dates: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * len(dates),
            "vwap": closes,
            "transactions": [1_000] * len(dates),
        }
    )


def _bundle(
    dates: pd.DatetimeIndex,
    closes_by_symbol: dict[str, list[float]],
    tradable_symbol: str = "QQQ",
) -> MarketDataBundle:
    return MarketDataBundle(
        tradable=_market_df(tradable_symbol, dates, closes_by_symbol[tradable_symbol]),
        references={
            symbol: _market_df(symbol, dates, closes)
            for symbol, closes in closes_by_symbol.items()
            if symbol != tradable_symbol
        },
    )


def _rotation_strategy(
    *,
    dates: pd.DatetimeIndex,
    top_n: int = 1,
    lookback: int = 5,
    transaction_cost_bps: float = 0.0,
    risk_filter: dict | None = None,
    fallback: dict | None = None,
    universe: list[str] | None = None,
    initial_capital: float = 10_000.0,
) -> StrategyV2:
    universe = universe or ["QQQ", "SPY", "XLK", "TLT"]
    return StrategyV2.model_validate(
        {
            "schema_version": "2.0",
            "name": "synthetic-rotation",
            "tradable_symbol": "QQQ",
            "benchmark_symbol": "SPY",
            "reference_symbols": [symbol for symbol in universe if symbol != "QQQ"],
            "start_date": str(date.fromisoformat(str(dates[0].date()))),
            "end_date": str(date.fromisoformat(str(dates[-1].date()))),
            "initial_capital": initial_capital,
            "transaction_cost_bps": transaction_cost_bps,
            "rotation": {
                "enabled": True,
                "universe": universe,
                "ranking": {
                    "type": "relative_return",
                    "lookback": lookback,
                    "descending": True,
                },
                "rebalance": {
                    "frequency": "monthly",
                    "day": "first_trading_day",
                },
                "selection": {"top_n": top_n},
                "allocation": {
                    "weighting": "equal_weight",
                    "max_position_pct": 1.0,
                },
                "risk_filter": risk_filter,
                "fallback": fallback or {"type": "cash"},
            },
        }
    )


def _trend_closes(dates: pd.DatetimeIndex, daily_step: float) -> list[float]:
    return [100.0 + (index * daily_step) for index in range(len(dates))]


def test_rotation_config_validates_without_single_symbol_rules() -> None:
    dates = pd.date_range("2021-01-01", periods=30, freq="B")

    strategy = _rotation_strategy(dates=dates)

    assert strategy.rotation is not None
    assert strategy.rotation.enabled is True
    assert strategy.allocation is None
    assert strategy.entry_rule is None
    assert "XLK" in strategy.rotation_required_reference_symbols()


def test_rotation_ranks_assets_by_trailing_return_and_selects_top_1() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    bundle = _bundle(
        dates,
        {
            "QQQ": _trend_closes(dates, 1.0),
            "SPY": _trend_closes(dates, 0.5),
            "XLK": _trend_closes(dates, 2.0),
            "TLT": _trend_closes(dates, -0.25),
        },
    )
    strategy = _rotation_strategy(dates=dates, top_n=1, lookback=5)

    result = run_simulation(bundle, strategy)
    feb_rebalance = next(
        row for row in result.timeline if row["date"] == "2021-02-01"
    )

    assert feb_rebalance["selected_assets"] == ["XLK"]
    assert feb_rebalance["asset_ranks"]["XLK"] == 1
    assert result.trade_log[0]["symbol"] == "XLK"
    assert result.trade_log[0]["action"] == "BUY"


def test_rotation_selects_top_2_equal_weight() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    bundle = _bundle(
        dates,
        {
            "QQQ": _trend_closes(dates, 1.0),
            "SPY": _trend_closes(dates, 0.5),
            "XLK": _trend_closes(dates, 2.0),
            "TLT": _trend_closes(dates, -0.25),
        },
    )
    strategy = _rotation_strategy(dates=dates, top_n=2, lookback=5)

    result = run_simulation(bundle, strategy)
    feb_rebalance = next(
        row for row in result.timeline if row["date"] == "2021-02-01"
    )

    assert feb_rebalance["selected_assets"] == ["XLK", "QQQ"]
    assert feb_rebalance["target_weights"] == {"XLK": 0.5, "QQQ": 0.5}
    assert {trade["symbol"] for trade in result.trade_log[:2]} == {"XLK", "QQQ"}


def test_rotation_monthly_rebalance_dates_are_deterministic() -> None:
    dates = pd.date_range("2021-01-01", periods=60, freq="B")
    bundle = _bundle(
        dates,
        {
            "QQQ": _trend_closes(dates, 1.0),
            "SPY": _trend_closes(dates, 0.5),
            "XLK": _trend_closes(dates, 2.0),
            "TLT": _trend_closes(dates, -0.25),
        },
    )
    strategy = _rotation_strategy(dates=dates, lookback=5)

    result = run_simulation(bundle, strategy)
    rebalance_dates = [row["date"] for row in result.timeline if row["rebalance"]]

    assert rebalance_dates == ["2021-01-01", "2021-02-01", "2021-03-01"]
    assert result.summary["rebalance_count"] == 3


def test_rotation_ranking_does_not_look_ahead_after_rebalance_date() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2021-01-29", "2021-02-01", "2021-02-02"]))
    bundle = _bundle(
        dates,
        {
            "QQQ": [100.0, 100.0, 200.0],
            "SPY": [100.0, 101.0, 101.0],
            "XLK": [100.0, 100.5, 100.5],
            "TLT": [100.0, 99.0, 99.0],
        },
    )
    strategy = _rotation_strategy(dates=dates, top_n=1, lookback=1)

    result = run_simulation(bundle, strategy)
    feb_rebalance = next(
        row for row in result.timeline if row["date"] == "2021-02-01"
    )

    assert feb_rebalance["selected_assets"] == ["SPY"]
    assert result.trade_log[0]["symbol"] == "SPY"


def test_rotation_falls_back_to_cash_when_risk_filter_fails() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    bundle = _bundle(
        dates,
        {
            "QQQ": _trend_closes(dates, 1.0),
            "SPY": _trend_closes(dates, -1.0),
            "XLK": _trend_closes(dates, 2.0),
            "TLT": _trend_closes(dates, 0.25),
        },
    )
    strategy = _rotation_strategy(
        dates=dates,
        lookback=5,
        risk_filter={
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 2,
        },
        fallback={"type": "cash"},
    )

    result = run_simulation(bundle, strategy)
    feb_rebalance = next(
        row for row in result.timeline if row["date"] == "2021-02-01"
    )

    assert feb_rebalance["risk_filter_passed"] is False
    assert feb_rebalance["fallback_used"] == "cash"
    assert result.trade_log == []
    assert result.timeline[-1]["cash"] == pytest.approx(10_000.0)


def test_rotation_falls_back_to_asset_when_configured() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    bundle = _bundle(
        dates,
        {
            "QQQ": _trend_closes(dates, 1.0),
            "SPY": _trend_closes(dates, -1.0),
            "XLK": _trend_closes(dates, 2.0),
            "TLT": _trend_closes(dates, 0.25),
        },
    )
    strategy = _rotation_strategy(
        dates=dates,
        lookback=5,
        risk_filter={
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 2,
        },
        fallback={"type": "asset", "symbol": "TLT"},
    )

    result = run_simulation(bundle, strategy)
    feb_rebalance = next(
        row for row in result.timeline if row["date"] == "2021-02-01"
    )

    assert feb_rebalance["selected_assets"] == ["TLT"]
    assert feb_rebalance["fallback_used"] == "TLT"
    assert result.trade_log[0]["symbol"] == "TLT"


def test_rotation_transaction_costs_apply_on_rebalance_trades() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2021-01-29", "2021-02-01"]))
    bundle = _bundle(
        dates,
        {
            "QQQ": [100.0, 100.0],
            "SPY": [100.0, 101.0],
            "XLK": [100.0, 102.0],
            "TLT": [100.0, 99.0],
        },
    )
    strategy = _rotation_strategy(
        dates=dates,
        top_n=1,
        lookback=1,
        transaction_cost_bps=100.0,
        initial_capital=1_000.0,
    )

    result = run_simulation(bundle, strategy)

    assert result.trade_log[0]["symbol"] == "XLK"
    assert result.trade_log[0]["fee"] == pytest.approx(9.18)
    assert result.timeline[-1]["overlay_fees_paid"] == pytest.approx(9.18)
    assert result.timeline[-1]["cash"] == pytest.approx(72.82)
