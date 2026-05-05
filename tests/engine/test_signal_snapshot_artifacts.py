from __future__ import annotations

import json

import pandas as pd

from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine.artifacts import write_artifacts
from market_simulator.engine.runner import run_simulation
from market_simulator.models.strategy_v2 import StrategyV2


def _tradable_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    closes = [100.0 - index for index in range(20)] + [80.0 + index for index in range(10)]
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "QQQ",
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": 1000,
        }
    )


def _base_config(entry_rule: dict, exit_rule: dict, reference_symbols: list[str] | None = None) -> dict:
    return {
        "schema_version": "2.0",
        "name": "signal-snapshot-test",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "QQQ",
        "reference_symbols": reference_symbols or [],
        "start_date": "2024-01-01",
        "end_date": "2024-01-30",
        "initial_capital": 10000,
        "transaction_cost_bps": 0,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": entry_rule,
        "exit_rule": exit_rule,
        "risk": {"cooldown_bars": 0},
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
    }


def _capital_context_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "QQQ",
            "open": [32.0, 8.5, 13.0],
            "high": [33.0, 9.0, 14.0],
            "low": [30.0, 8.0, 11.0],
            "close": [33.0, 9.0, 12.0],
            "volume": 1000,
        }
    )


def _capital_context_config() -> dict:
    config = _base_config(
        {
            "kind": "atomic",
            "type": "close_near_high",
            "symbol": "QQQ",
            "threshold": 0.2,
        },
        {
            "kind": "atomic",
            "type": "bearish_candle",
            "symbol": "QQQ",
        },
    )
    config["initial_capital"] = 100000
    config["position_management"] = {
        "scale_in_fraction": 1.0,
        "scale_out_fraction": 0.5,
    }
    return config


def test_rsi_rule_persists_symbol_qualified_value_in_timeline() -> None:
    strategy = StrategyV2.model_validate(
        _base_config(
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 35,
            },
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 95,
            },
        )
    )

    result = run_simulation(MarketDataBundle(tradable=_tradable_frame(), references={}), strategy)

    rsi_values = [row.get("QQQ_RSI_14") for row in result.timeline if row.get("QQQ_RSI_14") is not None]
    assert rsi_values
    assert result.trade_signal_snapshots
    assert result.trade_signal_snapshots[0]["signals"][0]["label"] == "QQQ RSI(14)"
    assert result.trade_signal_snapshots[0]["signals"][0]["actual"] == rsi_values[0]
    assert result.trade_signal_snapshots[0]["signals"][0]["actual_value"] == rsi_values[0]


def test_trade_signal_snapshots_include_buy_capital_context() -> None:
    strategy = StrategyV2.model_validate(_capital_context_config())

    result = run_simulation(MarketDataBundle(tradable=_capital_context_frame(), references={}), strategy)

    buy_snapshot = result.trade_signal_snapshots[0]
    capital_context = buy_snapshot["capital_context"]
    assert buy_snapshot["action"] == "BUY"
    assert capital_context["trade_notional"] == 99990.0
    assert capital_context["position_allocation_pct_after"] == 99.99
    assert capital_context["position_shares_before"] == 0
    assert capital_context["position_shares_after"] == 3030
    assert "trade_notional" not in result.trade_log[0]


def test_buy_add_snapshot_explains_tiny_add_near_full_allocation() -> None:
    strategy = StrategyV2.model_validate(_capital_context_config())

    result = run_simulation(MarketDataBundle(tradable=_capital_context_frame(), references={}), strategy)

    buy_add_snapshot = result.trade_signal_snapshots[1]
    capital_context = buy_add_snapshot["capital_context"]
    trade_size_pct = (
        capital_context["trade_notional"] / capital_context["equity_before_trade"]
    ) * 100
    assert buy_add_snapshot["action"] == "BUY_ADD"
    assert capital_context["trade_notional"] == 9.0
    assert trade_size_pct < 0.1
    assert capital_context["position_allocation_pct_after"] > 99.9
    assert capital_context["remaining_capacity_after"] > 0


def test_sell_reduce_snapshot_includes_position_after_and_trade_notional() -> None:
    strategy = StrategyV2.model_validate(_capital_context_config())

    result = run_simulation(MarketDataBundle(tradable=_capital_context_frame(), references={}), strategy)

    sell_snapshot = result.trade_signal_snapshots[2]
    capital_context = sell_snapshot["capital_context"]
    assert sell_snapshot["action"] == "SELL_REDUCE"
    assert capital_context["trade_notional"] == 18180.0
    assert capital_context["position_shares_before"] == 3031
    assert capital_context["position_shares_after"] == 1516
    assert capital_context["position_value_after"] == 18192.0


def test_series_below_rule_persists_reference_value_in_timeline() -> None:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    vix = pd.DataFrame(
        {
            "date": dates,
            "symbol": "VIX",
            "value": [30.0 - index for index in range(30)],
        }
    )
    strategy = StrategyV2.model_validate(
        _base_config(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 20,
            },
            {
                "kind": "atomic",
                "type": "series_above",
                "symbol": "VIX",
                "threshold": 100,
            },
            reference_symbols=["VIX"],
        )
    )

    result = run_simulation(
        MarketDataBundle(tradable=_tradable_frame(), references={"VIX": vix}),
        strategy,
    )

    assert "VIX_value" in result.timeline[0]
    assert result.timeline[0]["VIX_value"] == 30.0
    assert result.trade_signal_snapshots
    assert result.trade_signal_snapshots[0]["signals"][0]["label"] == "VIX"
    assert result.trade_signal_snapshots[0]["signals"][0]["actual"] < 20
    assert result.trade_signal_snapshots[0]["signals"][0]["actual_value"] < 20


def test_write_artifacts_writes_rsi_timeline_column_and_trade_signal_snapshots_json(tmp_path) -> None:
    strategy = StrategyV2.model_validate(
        _base_config(
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 35,
            },
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 95,
            },
        )
    )
    result = run_simulation(MarketDataBundle(tradable=_tradable_frame(), references={}), strategy)

    write_artifacts(result, tmp_path)

    timeline_header = (tmp_path / "timeline.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "QQQ_RSI_14" in timeline_header

    snapshot_path = tmp_path / "trade_signal_snapshots.json"
    assert snapshot_path.exists()
    snapshots = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshots[0]["signals"][0]["label"] == "QQQ RSI(14)"
    assert snapshots[0]["signals"][0]["actual"] == snapshots[0]["signals"][0]["actual_value"]


def test_write_artifacts_writes_vix_timeline_column_and_snapshot_actual(tmp_path) -> None:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    vix = pd.DataFrame(
        {
            "date": dates,
            "symbol": "VIX",
            "value": [30.0 - index for index in range(30)],
        }
    )
    strategy = StrategyV2.model_validate(
        _base_config(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 20,
            },
            {
                "kind": "atomic",
                "type": "series_above",
                "symbol": "VIX",
                "threshold": 100,
            },
            reference_symbols=["VIX"],
        )
    )
    result = run_simulation(
        MarketDataBundle(tradable=_tradable_frame(), references={"VIX": vix}),
        strategy,
    )

    write_artifacts(result, tmp_path)

    timeline_header = (tmp_path / "timeline.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "VIX_value" in timeline_header
    snapshots = json.loads((tmp_path / "trade_signal_snapshots.json").read_text(encoding="utf-8"))
    assert snapshots[0]["signals"][0]["label"] == "VIX"
    assert snapshots[0]["signals"][0]["actual"] < 20
