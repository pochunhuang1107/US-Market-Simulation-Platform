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
