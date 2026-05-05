from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from market_simulator.engine import runner
from market_simulator.models.strategy_v2 import StrategyV2


def _build_bundle() -> SimpleNamespace:
    return _build_bundle_with_closes([100.0, 110.0, 105.0, 108.0])


def _build_bundle_with_closes(closes: list[float]) -> SimpleNamespace:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2021-04-19", periods=len(closes), freq="D"),
            "close": closes,
        }
    )
    return SimpleNamespace(tradable=df)


def _build_strategy(
    *,
    position_management: dict | None = None,
) -> StrategyV2:
    config = {
        "schema_version": "2.0",
        "name": "spy-sma-cross-above-to-sma-cross-below",
        "tradable_symbol": "SPY",
        "benchmark_symbol": "SPY",
        "reference_symbols": [],
        "start_date": "2021-04-17",
        "end_date": "2021-04-30",
        "initial_capital": 1000,
        "transaction_cost_bps": 0,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "sma_cross_above",
            "symbol": "SPY",
            "fast_window": 5,
            "slow_window": 10,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "sma_cross_below",
            "symbol": "SPY",
            "fast_window": 5,
            "slow_window": 20,
        },
        "risk": {
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
    }

    if position_management is not None:
        config["position_management"] = position_management

    return StrategyV2.model_validate(config)


def _patch_runner_signals(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entry_indices: set[int],
    exit_indices: set[int] | None = None,
) -> None:
    exit_indices = exit_indices or set()

    def fake_enrich_market_data(input_bundle, _strategy):
        return input_bundle

    def fake_evaluate_rule(rule, _bundle, i, _tradable_symbol=None):
        rule_type = getattr(rule, "type", None)
        if rule_type == "sma_cross_above":
            return i in entry_indices
        if rule_type == "sma_cross_below":
            return i in exit_indices
        return False

    monkeypatch.setattr(runner, "enrich_market_data", fake_enrich_market_data)
    monkeypatch.setattr(runner, "evaluate_rule", fake_evaluate_rule)


def test_run_simulation_accepts_composite_rsi_and_price_sma_rule() -> None:
    dates = pd.date_range("2021-01-01", periods=260, freq="D")
    bundle = SimpleNamespace(
        tradable=pd.DataFrame(
            {
                "date": dates,
                "close": [100.0 + index * 0.1 for index in range(260)],
            }
        ),
        references={},
    )
    strategy = StrategyV2.model_validate(
        {
            "schema_version": "2.0",
            "name": "qqq-composite-smoke",
            "tradable_symbol": "QQQ",
            "benchmark_symbol": "QQQ",
            "reference_symbols": [],
            "start_date": "2021-01-01",
            "end_date": "2021-09-17",
            "initial_capital": 100000,
            "transaction_cost_bps": 0,
            "allocation": {
                "entry_mode": "percent_of_equity",
                "entry_value": 1.0,
                "max_position_pct": 1.0,
            },
            "entry_rule": {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 101,
                    },
                    {
                        "kind": "atomic",
                        "type": "sma_above",
                        "symbol": "QQQ",
                        "fast_window": 1,
                        "slow_window": 200,
                    },
                ],
            },
            "exit_rule": {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 101,
            },
            "risk": {"cooldown_bars": 0},
            "core_overlay": {
                "enabled": False,
                "core_allocation_pct": 0.0,
            },
        }
    )

    result = runner.run_simulation(bundle, strategy)

    assert len(result.timeline) == 260
    assert result.summary["ending_equity"] == 100000.0


def test_run_simulation_without_position_management_is_all_in_all_out(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _build_bundle()
    strategy = _build_strategy(position_management=None)

    def fake_enrich_market_data(input_bundle, _strategy):
        return input_bundle

    def fake_evaluate_rule(rule, _bundle, i, _tradable_symbol=None):
        rule_type = getattr(rule, "type", None)
        if rule_type == "sma_cross_above":
            return i == 0
        if rule_type == "sma_cross_below":
            return i == 1
        return False

    monkeypatch.setattr(runner, "enrich_market_data", fake_enrich_market_data)
    monkeypatch.setattr(runner, "evaluate_rule", fake_evaluate_rule)

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert actions == ["BUY", "SELL_ALL"]
    assert "BUY_ADD" not in actions
    assert "SELL_REDUCE" not in actions
    assert "SELL_REDUCE_PROFIT" not in actions


def test_run_simulation_without_position_management_does_not_profit_reduce(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _build_bundle()
    strategy = _build_strategy(position_management=None)

    def fake_enrich_market_data(input_bundle, _strategy):
        return input_bundle

    def fake_evaluate_rule(rule, _bundle, i, _tradable_symbol=None):
        rule_type = getattr(rule, "type", None)
        if rule_type == "sma_cross_above":
            return i == 0
        if rule_type == "sma_cross_below":
            return i == 3
        return False

    monkeypatch.setattr(runner, "enrich_market_data", fake_enrich_market_data)
    monkeypatch.setattr(runner, "evaluate_rule", fake_evaluate_rule)

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert actions[0] == "BUY"
    assert "SELL_REDUCE_PROFIT" not in actions
    assert "BUY_ADD" not in actions


def test_run_simulation_with_position_management_can_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _build_bundle()
    strategy = _build_strategy(
        position_management={
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "profit_reduce_threshold": 0.05,
        }
    )

    def fake_enrich_market_data(input_bundle, _strategy):
        return input_bundle

    def fake_evaluate_rule(rule, _bundle, i, _tradable_symbol=None):
        rule_type = getattr(rule, "type", None)
        if rule_type == "sma_cross_above":
            return i in {0, 1}
        if rule_type == "sma_cross_below":
            return i == 3
        return False

    monkeypatch.setattr(runner, "enrich_market_data", fake_enrich_market_data)
    monkeypatch.setattr(runner, "evaluate_rule", fake_evaluate_rule)

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert "BUY" in actions
    assert "BUY_ADD" in actions or "SELL_REDUCE_PROFIT" in actions or "SELL_REDUCE" in actions


def test_run_simulation_default_position_management_still_allows_repeated_buy_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle_with_closes([50.0] * 5)
    strategy = _build_strategy(
        position_management={
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
        }
    )
    _patch_runner_signals(monkeypatch, entry_indices={0, 1, 2, 3, 4})

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert actions == ["BUY", "BUY_ADD", "BUY_ADD", "BUY_ADD"]
    assert result.trade_signal_snapshots[1]["capital_context"]["trade_notional"] == 250.0
    assert result.trade_signal_snapshots[1]["signals"]


def test_run_simulation_max_scale_in_steps_caps_buy_add_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle_with_closes([100.0] * 6)
    strategy = _build_strategy(
        position_management={
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "max_scale_in_steps": 2,
        }
    )
    _patch_runner_signals(monkeypatch, entry_indices={0, 1, 2, 3, 4, 5})

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert actions == ["BUY", "BUY_ADD"]
    assert result.trade_signal_snapshots[-1]["scale_step_after"] == 2
    assert result.trade_signal_snapshots[-1]["max_scale_in_steps"] == 2


def test_run_simulation_min_bars_between_scale_ins_blocks_consecutive_buy_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle_with_closes([100.0] * 8)
    strategy = _build_strategy(
        position_management={
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "max_scale_in_steps": 4,
            "min_bars_between_scale_ins": 3,
        }
    )
    _patch_runner_signals(monkeypatch, entry_indices={0, 1, 2, 3, 4, 5, 6, 7})

    result = runner.run_simulation(bundle, strategy)
    buy_dates = [trade["date"] for trade in result.trade_log if trade["action"].startswith("BUY")]

    assert buy_dates == ["2021-04-19", "2021-04-22", "2021-04-25"]
    assert [snapshot["bars_since_last_scale_in"] for snapshot in result.trade_signal_snapshots] == [
        None,
        3,
        3,
    ]


def test_run_simulation_persistent_signal_requires_unbroken_entry_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle_with_closes([100.0] * 6)
    strategy = _build_strategy(
        position_management={
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "min_bars_between_scale_ins": 2,
            "scale_in_requires_persistent_signal": True,
        }
    )
    _patch_runner_signals(monkeypatch, entry_indices={0, 1, 3, 4, 5})

    result = runner.run_simulation(bundle, strategy)
    buy_dates = [trade["date"] for trade in result.trade_log if trade["action"].startswith("BUY")]

    assert buy_dates == ["2021-04-19", "2021-04-24"]


def test_run_simulation_full_exit_resets_scale_in_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle_with_closes([100.0] * 5)
    strategy = _build_strategy(
        position_management={
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 1.0,
            "max_scale_in_steps": 2,
        }
    )
    _patch_runner_signals(
        monkeypatch,
        entry_indices={0, 1, 3, 4},
        exit_indices={2},
    )

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert actions == ["BUY", "BUY_ADD", "SELL_ALL", "BUY", "BUY_ADD"]
    assert [snapshot.get("scale_step_after") for snapshot in result.trade_signal_snapshots] == [
        1,
        2,
        None,
        1,
        2,
    ]
