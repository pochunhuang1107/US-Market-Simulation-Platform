from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from market_simulator.engine import runner
from market_simulator.models.strategy_v2 import StrategyV2


def _build_bundle() -> SimpleNamespace:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2021-04-19", "2021-04-20", "2021-04-21", "2021-04-22"]
            ),
            "close": [100.0, 110.0, 105.0, 108.0],
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


def test_run_simulation_without_position_management_is_all_in_all_out(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _build_bundle()
    strategy = _build_strategy(position_management=None)

    def fake_enrich_market_data(input_bundle, _strategy):
        return input_bundle

    def fake_evaluate_rule(rule, _bundle, i):
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

    def fake_evaluate_rule(rule, _bundle, i):
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

    def fake_evaluate_rule(rule, _bundle, i):
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