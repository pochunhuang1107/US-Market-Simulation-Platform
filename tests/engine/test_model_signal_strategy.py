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
    closes_by_symbol: dict[str, list[float]] | None = None,
) -> MarketDataBundle:
    closes_by_symbol = closes_by_symbol or {
        "QQQ": [100.0 + index for index in range(len(dates))],
        "SPY": [100.0 + index * 0.5 for index in range(len(dates))],
        "XLK": [100.0 + index * 1.5 for index in range(len(dates))],
        "TLT": [100.0 - index * 0.1 for index in range(len(dates))],
    }
    return MarketDataBundle(
        tradable=_market_df("QQQ", dates, closes_by_symbol["QQQ"]),
        references={
            symbol: _market_df(symbol, dates, closes)
            for symbol, closes in closes_by_symbol.items()
            if symbol != "QQQ"
        },
    )


def _strategy(
    dates: pd.DatetimeIndex,
    *,
    top_n: int = 1,
    fallback: dict | None = None,
    min_confidence: float | None = None,
    signal_bucket_filter: list[str] | None = None,
    universe: list[str] | None = None,
) -> StrategyV2:
    model_signal: dict = {
        "enabled": True,
        "model_version": "ml_v1",
        "ranking_field": "score",
        "universe": universe or ["QQQ", "SPY", "XLK", "TLT"],
        "top_n": top_n,
        "rebalance": {
            "frequency": "monthly",
            "day": "first_trading_day",
        },
        "fallback": fallback or {"type": "cash"},
    }
    if min_confidence is not None:
        model_signal["min_confidence"] = min_confidence
    if signal_bucket_filter is not None:
        model_signal["signal_bucket_filter"] = signal_bucket_filter

    return StrategyV2.model_validate(
        {
            "schema_version": "2.0",
            "name": "synthetic-model-signal",
            "tradable_symbol": "QQQ",
            "benchmark_symbol": "SPY",
            "reference_symbols": ["SPY", "XLK", "TLT"],
            "start_date": str(date.fromisoformat(str(dates[0].date()))),
            "end_date": str(date.fromisoformat(str(dates[-1].date()))),
            "initial_capital": 10_000.0,
            "transaction_cost_bps": 0.0,
            "model_signal": model_signal,
        }
    )


def _signals(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [row["date"] for row in rows],
            "symbol": [row["symbol"] for row in rows],
            "model_version": [row.get("model_version", "ml_v1") for row in rows],
            "score": [row["score"] for row in rows],
            **(
                {"confidence": [row.get("confidence") for row in rows]}
                if any("confidence" in row for row in rows)
                else {}
            ),
            **(
                {"signal_bucket": [row.get("signal_bucket") for row in rows]}
                if any("signal_bucket" in row for row in rows)
                else {}
            ),
        }
    )


def test_model_signal_config_validates_without_single_symbol_rules() -> None:
    dates = pd.date_range("2021-01-01", periods=30, freq="B")

    strategy = _strategy(dates, top_n=2)

    assert strategy.model_signal is not None
    assert strategy.model_signal.enabled is True
    assert strategy.allocation is None
    assert strategy.entry_rule is None
    assert strategy.model_signal_required_reference_symbols() == ["SPY", "TLT", "XLK"]


def test_disabled_model_signal_block_is_backwards_compatible() -> None:
    dates = pd.date_range("2021-01-01", periods=30, freq="B")

    strategy = StrategyV2.model_validate(
        {
            "schema_version": "2.0",
            "name": "disabled-model-signal",
            "tradable_symbol": "QQQ",
            "benchmark_symbol": "SPY",
            "reference_symbols": ["SPY"],
            "start_date": str(date.fromisoformat(str(dates[0].date()))),
            "end_date": str(date.fromisoformat(str(dates[-1].date()))),
            "initial_capital": 10_000.0,
            "transaction_cost_bps": 0.0,
            "allocation": {"entry_value": 1.0},
            "entry_rule": {
                "kind": "atomic",
                "type": "rsi_below",
                "lookback": 14,
                "threshold": 30,
            },
            "exit_rule": {
                "kind": "atomic",
                "type": "rsi_above",
                "lookback": 14,
                "threshold": 70,
            },
            "model_signal": {"enabled": False},
        }
    )

    assert strategy.model_signal is not None
    assert strategy.model_signal.enabled is False


def test_model_signal_ranks_assets_by_score_and_selects_top_1() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    result = run_simulation(
        _bundle(dates),
        _strategy(dates),
        model_signal_frame=_signals(
            [
                {"date": "2021-01-29", "symbol": "QQQ", "score": 0.2},
                {"date": "2021-01-29", "symbol": "SPY", "score": 0.1},
                {"date": "2021-01-29", "symbol": "XLK", "score": 0.9},
                {"date": "2021-01-29", "symbol": "TLT", "score": -0.1},
            ]
        ),
    )

    feb_rebalance = next(row for row in result.timeline if row["date"] == "2021-02-01")

    assert feb_rebalance["selected_assets"] == ["XLK"]
    assert feb_rebalance["model_scores"]["XLK"] == 0.9
    assert feb_rebalance["model_ranks"]["XLK"] == 1
    assert feb_rebalance["model_version"] == "ml_v1"
    assert result.trade_log[0]["symbol"] == "XLK"


def test_model_signal_selects_top_2_equal_weight() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    result = run_simulation(
        _bundle(dates),
        _strategy(dates, top_n=2),
        model_signal_frame=_signals(
            [
                {"date": "2021-01-29", "symbol": "QQQ", "score": 0.8},
                {"date": "2021-01-29", "symbol": "SPY", "score": 0.1},
                {"date": "2021-01-29", "symbol": "XLK", "score": 0.9},
                {"date": "2021-01-29", "symbol": "TLT", "score": -0.1},
            ]
        ),
    )
    feb_rebalance = next(row for row in result.timeline if row["date"] == "2021-02-01")

    assert feb_rebalance["selected_assets"] == ["XLK", "QQQ"]
    assert feb_rebalance["target_weights"] == {"XLK": 0.5, "QQQ": 0.5}
    assert {trade["symbol"] for trade in result.trade_log[:2]} == {"XLK", "QQQ"}


def test_model_signal_monthly_rebalance_dates_are_deterministic() -> None:
    dates = pd.date_range("2021-01-01", periods=60, freq="B")
    result = run_simulation(
        _bundle(dates),
        _strategy(dates),
        model_signal_frame=_signals(
            [
                {"date": "2021-01-01", "symbol": "QQQ", "score": 1.0},
                {"date": "2021-01-01", "symbol": "SPY", "score": 0.5},
                {"date": "2021-01-01", "symbol": "XLK", "score": 0.3},
                {"date": "2021-01-01", "symbol": "TLT", "score": 0.1},
            ]
        ),
    )

    assert [row["date"] for row in result.timeline if row["rebalance"]] == [
        "2021-01-01",
        "2021-02-01",
        "2021-03-01",
    ]
    assert result.summary["strategy_type"] == "model_signal"
    assert result.summary["rebalance_count"] == 3


def test_model_signal_rebalance_does_not_use_future_signal_rows() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2021-01-29", "2021-02-01", "2021-02-02"]))
    result = run_simulation(
        _bundle(dates),
        _strategy(dates),
        model_signal_frame=_signals(
            [
                {"date": "2021-01-29", "symbol": "QQQ", "score": 0.2},
                {"date": "2021-01-29", "symbol": "SPY", "score": 0.7},
                {"date": "2021-02-02", "symbol": "XLK", "score": 10.0},
                {"date": "2021-01-29", "symbol": "TLT", "score": 0.1},
            ]
        ),
    )

    feb_rebalance = next(row for row in result.timeline if row["date"] == "2021-02-01")

    assert feb_rebalance["selected_assets"] == ["SPY"]
    assert "XLK" not in feb_rebalance["model_scores"]
    assert result.trade_log[0]["symbol"] == "SPY"


def test_model_signal_falls_back_to_cash_when_no_eligible_signals() -> None:
    dates = pd.date_range("2021-01-01", periods=5, freq="B")
    result = run_simulation(
        _bundle(dates),
        _strategy(dates),
        model_signal_frame=_signals(
            [{"date": "2021-02-01", "symbol": "QQQ", "score": 1.0}]
        ),
    )

    assert result.timeline[0]["selected_assets"] == []
    assert result.timeline[0]["fallback_used"] == "cash"
    assert result.trade_log == []
    assert result.timeline[-1]["cash"] == pytest.approx(10_000.0)


def test_model_signal_falls_back_to_asset_when_configured() -> None:
    dates = pd.date_range("2021-01-01", periods=5, freq="B")
    result = run_simulation(
        _bundle(dates),
        _strategy(dates, fallback={"type": "asset", "symbol": "TLT"}),
        model_signal_frame=_signals(
            [{"date": "2021-02-01", "symbol": "QQQ", "score": 1.0}]
        ),
    )

    assert result.timeline[0]["selected_assets"] == ["TLT"]
    assert result.timeline[0]["fallback_used"] == "TLT"
    assert result.trade_log[0]["symbol"] == "TLT"


def test_model_signal_min_confidence_filters_low_confidence_rows() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    result = run_simulation(
        _bundle(dates),
        _strategy(dates, min_confidence=0.8),
        model_signal_frame=_signals(
            [
                {"date": "2021-01-29", "symbol": "QQQ", "score": 10.0, "confidence": 0.4},
                {"date": "2021-01-29", "symbol": "SPY", "score": 0.7, "confidence": 0.9},
                {"date": "2021-01-29", "symbol": "XLK", "score": 0.6, "confidence": 0.7},
                {"date": "2021-01-29", "symbol": "TLT", "score": 0.1, "confidence": 0.8},
            ]
        ),
    )
    feb_rebalance = next(row for row in result.timeline if row["date"] == "2021-02-01")

    assert feb_rebalance["selected_assets"] == ["SPY"]
    assert feb_rebalance["model_scores"] == {"SPY": 0.7, "TLT": 0.1}


def test_model_signal_bucket_filter_limits_eligible_rows() -> None:
    dates = pd.date_range("2021-01-01", periods=45, freq="B")
    result = run_simulation(
        _bundle(dates),
        _strategy(dates, signal_bucket_filter=["top"]),
        model_signal_frame=_signals(
            [
                {"date": "2021-01-29", "symbol": "QQQ", "score": 10.0, "signal_bucket": "middle"},
                {"date": "2021-01-29", "symbol": "SPY", "score": 0.7, "signal_bucket": "top"},
                {"date": "2021-01-29", "symbol": "XLK", "score": 0.6, "signal_bucket": "bottom"},
                {"date": "2021-01-29", "symbol": "TLT", "score": 0.1, "signal_bucket": "top"},
            ]
        ),
    )
    feb_rebalance = next(row for row in result.timeline if row["date"] == "2021-02-01")

    assert feb_rebalance["selected_assets"] == ["SPY"]
    assert feb_rebalance["model_scores"] == {"SPY": 0.7, "TLT": 0.1}


def test_model_signal_unsupported_config_symbol_is_rejected() -> None:
    dates = pd.date_range("2021-01-01", periods=30, freq="B")

    with pytest.raises(ValueError, match="unsupported ETF symbols: NOTETF"):
        _strategy(dates, universe=["QQQ", "NOTETF"])
