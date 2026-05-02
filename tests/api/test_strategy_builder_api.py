from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
import market_simulator.services.strategy_builder_service as builder_service
import market_simulator.services.strategy_builder_parsers as builder_parsers
import market_simulator.services.strategy_builder_response as builder_response
from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine import runner
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.parameter_sweep import (
    generate_variant_configs,
    get_nested,
)
from market_simulator.strategy.enricher import enrich_market_data
from market_simulator.strategy.evaluator import evaluate_rule
from market_simulator.settings import get_settings
from market_simulator.db.models import Plan


@pytest.fixture(autouse=True)
def default_builder_test_user(create_user, current_user_ctx):
    create_user(
        user_id=current_user_ctx["id"],
        email="builder-test@example.com",
    )


@pytest.fixture(autouse=True)
def default_builder_metadata_lookup(monkeypatch):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)


def _qqq_rsi_core_overlay_current_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-rsi-core-overlay-test",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": [],
        "start_date": "2019-01-02",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 0.4,
            "max_position_pct": 0.4,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 30,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 70,
        },
        "risk": {
            "stop_loss_pct": 0.08,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": True,
            "core_allocation_pct": 0.6,
        },
        "position_management": {
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "profit_reduce_threshold": 0.05,
        },
    }


def _qqq_sma_current_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-sma-test",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": [],
        "start_date": "2021-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "sma_cross_above",
            "symbol": "QQQ",
            "fast_window": 10,
            "slow_window": 30,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "sma_cross_below",
            "symbol": "QQQ",
            "fast_window": 10,
            "slow_window": 30,
        },
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
        "position_management": None,
    }


def test_generate_strategy_builder_follow_up_rsi_sweep_uses_current_config(client):
    current_config = _qqq_rsi_core_overlay_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70. Rank by Sharpe.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"] == current_config
    assert sweep["grid"] == {
        "entry_rule.threshold": [20, 25, 30],
        "exit_rule.threshold": [60, 65, 70],
    }
    assert sweep["ranking_metric"] == "sharpe_ratio"
    assert sweep["variant_count"] == 9


def test_generate_strategy_builder_follow_up_rsi_range_sweep_uses_current_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Sweep RSI buy threshold from 20 to 30 and sell threshold 60 to 70.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {
        "entry_rule.threshold": [20, 25, 30],
        "exit_rule.threshold": [60, 65, 70],
    }
    assert sweep["variant_count"] == 9


def test_generate_strategy_builder_follow_up_sma_sweep_uses_sma_paths(client):
    current_config = _qqq_sma_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry slow windows 10, 20 and exit slow windows 20, 30.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"] == current_config
    assert sweep["grid"] == {
        "entry_rule.slow_window": [10, 20],
        "exit_rule.slow_window": [20, 30],
    }
    assert "entry_rule.threshold" not in sweep["grid"]
    assert "exit_rule.threshold" not in sweep["grid"]
    assert sweep["variant_count"] == 4


def test_generate_strategy_builder_follow_up_risk_sweep_parses_percent_and_cooldown(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try stop loss 5%, 10% and take profit 10%, 15% and cooldown 0, 5 bars.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {
        "risk.stop_loss_pct": [0.05, 0.1],
        "risk.take_profit_pct": [0.1, 0.15],
        "risk.cooldown_bars": [0, 5],
    }
    assert sweep["variant_count"] == 8


def test_generate_strategy_builder_follow_up_sweep_ranking_metric_total_return(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry thresholds 20, 25 and exit thresholds 60, 65. Rank by total return.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert body["sweep_draft"]["ranking_metric"] == "total_return_pct"


def test_generate_strategy_builder_follow_up_sweep_over_limit_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Try entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70 "
                "and stop loss 5%, 10%, 15%."
            ),
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == "This sweep would create 27 variants, but your plan allows up to 25."


def test_generate_strategy_builder_follow_up_mismatched_parameter_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try RSI thresholds 20, 30.",
            "context": {"current_config": _qqq_sma_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == (
        "This draft does not use RSI rules yet. You can create an RSI strategy first, "
        "or ask me to replace the entry/exit rules with RSI."
    )


def test_generate_strategy_builder_existing_sweep_allows_simple_grid_and_ranking_edits(client):
    current_sweep = {
        "title": "QQQ RSI Threshold Sweep",
        "base_config": _qqq_rsi_core_overlay_current_config(),
        "grid": {
            "entry_rule.threshold": [20, 25],
            "exit_rule.threshold": [60, 65],
        },
        "ranking_metric": "sharpe_ratio",
        "variant_count": 4,
        "max_variants": 25,
        "summary": "Existing sweep draft.",
    }

    add_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Add entry threshold 35.",
            "context": {"current_config": current_sweep},
        },
    )

    assert add_response.status_code == 200
    add_body = add_response.json()
    assert add_body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert add_body["sweep_draft"]["grid"]["entry_rule.threshold"] == [20, 25, 35]
    assert add_body["sweep_draft"]["variant_count"] == 6

    rank_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Rank by total return.",
            "context": {"current_config": add_body["sweep_draft"]},
        },
    )

    assert rank_response.status_code == 200
    rank_body = rank_response.json()
    assert rank_body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert rank_body["sweep_draft"]["ranking_metric"] == "total_return_pct"


def test_generate_strategy_builder_returns_rsi_parameter_sweep_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Test QQQ RSI entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70 "
                "from 2021-01-01 to 2024-12-31. Rank by Sharpe."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert body["config"] is None
    assert sweep["base_config"]["tradable_symbol"] == "QQQ"
    assert sweep["base_config"]["entry_rule"]["type"] == "rsi_below"
    assert sweep["base_config"]["exit_rule"]["type"] == "rsi_above"
    assert sweep["base_config"]["start_date"] == "2021-01-01"
    assert sweep["base_config"]["end_date"] == "2024-12-31"
    assert sweep["grid"] == {
        "entry_rule.threshold": [20, 25, 30],
        "exit_rule.threshold": [60, 65, 70],
    }
    assert sweep["ranking_metric"] == "sharpe_ratio"
    assert sweep["variant_count"] == 9
    assert sweep["max_variants"] == 25


def test_generate_strategy_builder_returns_sma_parameter_sweep_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try QQQ SMA fast windows 5, 10 and slow windows 20, 30",
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"]["entry_rule"]["type"] == "sma_cross_above"
    assert sweep["base_config"]["exit_rule"]["type"] == "sma_cross_below"
    assert sweep["grid"] == {
        "entry_rule.fast_window": [5, 10],
        "entry_rule.slow_window": [20, 30],
    }
    assert sweep["variant_count"] == 4


def test_generate_strategy_builder_parameter_sweep_ranking_metric_total_return(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Test QQQ RSI entry thresholds 20, 25 and exit thresholds 60, 65. "
                "Rank by total return."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert body["sweep_draft"]["ranking_metric"] == "total_return_pct"


def test_generate_strategy_builder_parameter_sweep_over_limit_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Test QQQ RSI entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70 "
                "and stop loss 5%, 10%, 15%. Rank by Sharpe."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == "This sweep would create 27 variants, but your plan allows up to 25."


def test_generate_strategy_builder_normal_rsi_prompt_still_returns_strategy_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a simple RSI strategy for QQQ."},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "CREATE_DRAFT"
    assert body["sweep_draft"] is None
    assert body["config"]["entry_rule"]["type"] == "rsi_below"


def test_generate_strategy_builder_parses_bullish_candle_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes above its open."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "bullish_candle",
        "symbol": "QQQ",
    }
    assert "Enter when QQQ closes above its open." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_previous_low_exit_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes below yesterday's low."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "close_below_previous_low",
        "symbol": "QQQ",
    }
    assert "Exit when QQQ closes below the previous day's low." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_defaults_near_high_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes near the high of the day."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "close_near_high",
        "symbol": "QQQ",
        "threshold": 0.2,
    }
    assert "QQQ closes in the top 20% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_defaults_near_low_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes near the low of the day."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "close_near_low",
        "symbol": "QQQ",
        "threshold": 0.2,
    }
    assert "QQQ closes in the bottom 20% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_top_range_percentage_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes in the top 10% of the day's range."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "close_near_high",
        "symbol": "QQQ",
        "threshold": 0.1,
    }
    assert "QQQ closes in the top 10% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        not in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_bottom_range_percentage_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes in the bottom 15% of the day's range."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "close_near_low",
        "symbol": "QQQ",
        "threshold": 0.15,
    }
    assert "QQQ closes in the bottom 15% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        not in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_within_candle_percentage_thresholds(client):
    top_response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes within the top 10% of the candle."},
    )
    bottom_response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes within the bottom 15% of the candle."},
    )

    assert top_response.status_code == 200
    assert bottom_response.status_code == 200
    top_config = top_response.json()["config"]
    bottom_config = bottom_response.json()["config"]

    assert top_config["entry_rule"]["type"] == "close_near_high"
    assert top_config["entry_rule"]["threshold"] == 0.1
    assert bottom_config["exit_rule"]["type"] == "close_near_low"
    assert bottom_config["exit_rule"]["threshold"] == 0.15
    StrategyV2.model_validate(top_config)
    StrategyV2.model_validate(bottom_config)


def test_generate_strategy_builder_parses_bullish_entry_and_previous_low_exit_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when QQQ closes above its open. "
                "Sell when QQQ closes below yesterday's low."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "bullish_candle"
    assert config["exit_rule"]["type"] == "close_below_previous_low"
    assert "Enter when QQQ closes above its open." in body["summary"]
    assert "Exit when QQQ closes below the previous day's low." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_adds_candle_rule_symbol_to_reference_symbols(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when SPY closes above its open."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "bullish_candle"
    assert config["entry_rule"]["symbol"] == "SPY"
    assert config["reference_symbols"] == ["SPY"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_composite_entry_and_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when RSI 14 is below 30 and QQQ is above its 200-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert config["entry_rule"]["rules"][1] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "QQQ",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert "Enter when QQQ RSI(14) is below 30 and QQQ price is above its 200-day SMA." in body["summary"]
    assert "Exit when QQQ RSI(14) is above 70." in body["summary"]


def test_generate_strategy_builder_composite_rsi_and_daily_candle_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when RSI is below 30 and QQQ closes near the high of the day. "
                "Sell when RSI is above 70 or QQQ closes below yesterday's low."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][0]["symbol"] == "QQQ"
    assert config["entry_rule"]["rules"][0]["threshold"] == 30.0
    assert config["entry_rule"]["rules"][1] == {
        "kind": "atomic",
        "type": "close_near_high",
        "symbol": "QQQ",
        "threshold": 0.2,
    }
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][0]["symbol"] == "QQQ"
    assert config["exit_rule"]["rules"][0]["threshold"] == 70.0
    assert config["exit_rule"]["rules"][1] == {
        "kind": "atomic",
        "type": "close_below_previous_low",
        "symbol": "QQQ",
    }
    assert "QQQ closes in the top 20% of the day's range" in body["summary"]
    assert "QQQ closes below the previous day's low" in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_simple_price_above_sma_prompt_uses_requested_window(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ is above its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "QQQ",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert "Enter when QQQ price is above its 200-day SMA." in body["summary"]
    assert "20-day SMA" not in body["summary"]
    assert "50-day SMA" not in body["summary"]


def test_generate_strategy_builder_follow_up_sma_sweep_targets_price_sma_window(client):
    draft_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ is above its 200-day SMA."
            ),
        },
    )
    assert draft_response.status_code == 200
    current_config = draft_response.json()["config"]

    sweep_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try SMA windows 100, 150, 200.",
            "context": {"current_config": current_config},
        },
    )

    assert sweep_response.status_code == 200
    body = sweep_response.json()
    sweep = body["sweep_draft"]
    path = "entry_rule.slow_window"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [100, 150, 200]}
    assert get_nested(sweep["base_config"], path) == 200

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [100, 150, 200]
    assert {variant["config"]["entry_rule"]["fast_window"] for variant in variants} == {1}


def test_generate_strategy_builder_composite_explicit_symbol_sma_crossover_preserves_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ 20-day SMA crosses above QQQ 50-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_cross_above",
        "symbol": "QQQ",
        "fast_window": 20,
        "slow_window": 50,
    }
    assert "Enter when QQQ 20-day SMA crosses above QQQ 50-day SMA." in body["summary"]
    assert "QQQ crosses above its 20-day SMA" not in body["summary"]
    assert "QQQ price is above its 20-day SMA" not in body["summary"]


def test_generate_strategy_builder_composite_explicit_sma_crossover_preserves_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when 20-day SMA crosses above 50-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 20
    assert config["entry_rule"]["slow_window"] == 50
    assert "Enter when QQQ 20-day SMA crosses above QQQ 50-day SMA." in body["summary"]


def test_generate_strategy_builder_composite_explicit_sma_cross_below_preserves_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ 50-day SMA crosses below QQQ 200-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_cross_below",
        "symbol": "QQQ",
        "fast_window": 50,
        "slow_window": 200,
    }
    assert "Enter when QQQ 50-day SMA crosses below QQQ 200-day SMA." in body["summary"]


def test_generate_strategy_builder_composite_exit_or_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when RSI 14 is below 30. "
                "Sell QQQ when RSI 14 is above 70 or QQQ is below its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "QQQ",
            "fast_window": 1,
            "slow_window": 200,
        },
    }
    assert "Exit when QQQ RSI(14) is above 70 or QQQ price is no longer above its 200-day SMA." in body["summary"]


def test_generate_strategy_builder_simple_price_below_sma_exit_prompt_uses_requested_window(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Sell when QQQ falls below its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "QQQ",
            "fast_window": 1,
            "slow_window": 200,
        },
    }
    assert "Exit when QQQ price is no longer above its 200-day SMA." in body["summary"]
    assert "20-day SMA" not in body["summary"]
    assert "50-day SMA" not in body["summary"]


def test_generate_strategy_builder_composite_reference_symbol_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy. "
                "Buy when QQQ RSI is below 30 and SPY is above its 200 day SMA. "
                "Sell when QQQ RSI is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert "SPY" in config["reference_symbols"]
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["rules"][1]["symbol"] == "SPY"
    assert config["entry_rule"]["rules"][1]["type"] == "sma_above"


def test_generate_strategy_builder_reference_symbol_trend_filter_with_rsi(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy that buys when RSI is below 30 and "
                "SPY is above its 200-day SMA. Sell when RSI is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]
    entry_rules = config["entry_rule"]["rules"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["name"] == "qqq-rsi-with-spy-trend-filter"
    assert config["name"] != "qqq-and-to-rsi-above"
    assert config["tradable_symbol"] == "QQQ"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert entry_rules[0] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert entry_rules[1] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70.0,
    }
    assert "Enter when QQQ RSI(14) is below 30 and SPY price is above its 200-day SMA." in body["summary"]
    assert "Exit when QQQ RSI(14) is above 70." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_entry_only_reference_symbol_trend_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Trade QQQ only when SPY is above its 200-day SMA."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert config["exit_rule"] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 200,
        },
    }
    assert "Enter when SPY price is above its 200-day SMA." in body["summary"]
    assert "Exit when SPY price is no longer above its 200-day SMA." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_vix_entry_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when VIX is below 25."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 25.0,
    }
    assert "VIX" in config["reference_symbols"]
    assert "Enter when VIX is below 25." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_composite_rsi_and_vix_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Only trade QQQ when VIX is below 25 and RSI is below 35.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]
    entry_rules = config["entry_rule"]["rules"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["name"] == "QQQ VIX + RSI Strategy"
    assert config["name"] != "qqq-and-to-rsi-above"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert entry_rules[0] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 25.0,
    }
    assert entry_rules[1] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 35.0,
    }
    assert "VIX" in config["reference_symbols"]
    strategy = StrategyV2.model_validate(config)

    bundle = MarketDataBundle(
        tradable=pd.DataFrame(
            {
                "date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"]),
                "symbol": ["QQQ", "QQQ", "QQQ"],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.0, 101.0, 102.0],
                "volume": [1_000_000.0, 1_000_000.0, 1_000_000.0],
                "vwap": [100.0, 101.0, 102.0],
                "transactions": [10_000.0, 10_000.0, 10_000.0],
                "rsi_14": [30.0, 30.0, 30.0],
            }
        ),
        references={
            "VIX": pd.DataFrame(
                {
                    "date": pd.to_datetime(["2021-01-04", "2021-01-06"]),
                    "symbol": ["VIX", "VIX"],
                    "value": [30.0, 20.0],
                }
            )
        },
    )

    result = runner.run_simulation(bundle, strategy)

    assert [row["entry_signal"] for row in result.timeline] == [False, False, True]
    assert result.timeline[1]["action_taken"] == ""


def test_generate_strategy_builder_parses_vix_exit_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when VIX is above 35."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "VIX",
        "threshold": 35.0,
    }
    assert "VIX" in config["reference_symbols"]
    assert "Exit when VIX is above 35." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_10y_yield_alias(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when the 10Y yield is below 4.5%."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "DGS10",
        "threshold": 4.5,
    }
    assert "DGS10" in config["reference_symbols"]
    assert "Enter when the 10-year Treasury yield is below 4.5%." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_inverted_yield_curve(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when the yield curve is inverted."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "T10Y2Y",
        "threshold": 0.0,
    }
    assert "T10Y2Y" in config["reference_symbols"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_t10y2y_direct_above_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when T10Y2Y is above 0."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "T10Y2Y",
        "threshold": 0.0,
    }
    assert "T10Y2Y" in config["reference_symbols"]
    assert "Enter when the 10Y-2Y Treasury spread is above 0." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_avoid_inverted_yield_curve_uses_safe_side(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Avoid risk-on entries when the yield curve is inverted."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "T10Y2Y",
        "threshold": 0.0,
    }
    assert "T10Y2Y" in config["reference_symbols"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_avoid_vix_above_uses_safe_side(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Avoid trading QQQ when VIX is above 30."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 30.0,
    }
    assert config["exit_rule"] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "series_below",
            "symbol": "VIX",
            "threshold": 30.0,
        },
    }
    assert "VIX" in config["reference_symbols"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_unsupported_macro_symbol_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when MOVE is below 120."},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "VIX, VIX9D, VXEEM, DGS10, DGS2, T10Y2Y, and DFF" in body["message"]


def test_generate_strategy_builder_keeps_rule_symbol_reference_when_it_is_also_benchmark(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy benchmark SPY. "
                "Trade QQQ only when SPY is above its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"]["symbol"] == "SPY"
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_mixed_tradable_and_reference_sma_filters(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when QQQ is above its 50-day SMA and "
                "SPY is above its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]
    entry_rules = config["entry_rule"]["rules"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert entry_rules[0] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "QQQ",
        "fast_window": 1,
        "slow_window": 50,
    }
    assert entry_rules[1] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_composite_follow_up_edits_and_sweep(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    threshold_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change RSI entry threshold to 25",
            "context": {"current_config": current_config},
        },
    )
    assert threshold_response.status_code == 200
    threshold_config = threshold_response.json()["config"]
    assert threshold_config["entry_rule"]["rules"][0]["threshold"] == 25

    sma_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change SMA filter to 150 days",
            "context": {"current_config": threshold_config},
        },
    )
    assert sma_response.status_code == 200
    sma_config = sma_response.json()["config"]
    assert sma_config["entry_rule"]["rules"][1]["slow_window"] == 150

    sweep_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry thresholds 20, 25, 30.",
            "context": {"current_config": sma_config},
        },
    )
    assert sweep_response.status_code == 200
    sweep_body = sweep_response.json()
    assert sweep_body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep_body["sweep_draft"]["grid"] == {
        "entry_rule.rules[0].threshold": [20, 25, 30],
    }


def test_generate_strategy_builder_follow_up_sweep_targets_entry_rsi_inside_composite_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try RSI entry thresholds 25, 30, 35.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "entry_rule.rules[0].threshold"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [25, 30, 35]}
    assert get_nested(sweep["base_config"], path) == 30

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [25, 30, 35]
    assert {variant["config"]["exit_rule"]["threshold"] for variant in variants} == {70}


def test_generate_strategy_builder_follow_up_sweep_targets_exit_rsi_inside_composite_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["exit_rule"] = {
        "kind": "group",
        "operator": "OR",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 70,
            },
            {
                "kind": "not",
                "rule": {
                    "kind": "atomic",
                    "type": "sma_above",
                    "symbol": "QQQ",
                    "fast_window": 1,
                    "slow_window": 200,
                },
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try exit RSI thresholds 65, 70, 75.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "exit_rule.rules[0].threshold"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [65, 70, 75]}
    assert get_nested(sweep["base_config"], path) == 70

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [65, 70, 75]
    assert {variant["config"]["entry_rule"]["threshold"] for variant in variants} == {30}


def test_generate_strategy_builder_follow_up_sweep_targets_sma_lookback_inside_composite_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try SMA windows 100, 150, 200.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "entry_rule.rules[1].slow_window"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [100, 150, 200]}
    assert get_nested(sweep["base_config"], path) == 200

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [100, 150, 200]
    assert {variant["config"]["entry_rule"]["rules"][1]["fast_window"] for variant in variants} == {1}
    assert {variant["config"]["entry_rule"]["rules"][0]["threshold"] for variant in variants} == {30}


def test_generate_strategy_builder_follow_up_sweep_targets_sma_inside_nested_exit_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["exit_rule"] = {
        "kind": "group",
        "operator": "OR",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 70,
            },
            {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "sma_above",
                        "symbol": "QQQ",
                        "fast_window": 1,
                        "slow_window": 200,
                    },
                    {
                        "kind": "atomic",
                        "type": "macd_bearish_cross",
                        "symbol": "QQQ",
                    },
                ],
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try exit SMA windows 100, 150, 200.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "exit_rule.rules[1].rules[0].slow_window"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [100, 150, 200]}
    assert get_nested(sweep["base_config"], path) == 200

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [100, 150, 200]
    assert {variant["config"]["exit_rule"]["rules"][0]["threshold"] for variant in variants} == {70}


def test_generate_strategy_builder_follow_up_sweep_ambiguous_duplicate_indicator_returns_guidance(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            current_config["entry_rule"],
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try RSI thresholds 25, 30, 35.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert "multiple possible" in body["message"]
    assert "entry/buy rule or the exit/sell rule" in body["message"]


def test_generate_strategy_builder_follow_up_sweep_missing_target_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try SMA windows 100, 150, 200.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == (
        "This draft does not use SMA rules yet. You can create an SMA strategy first, "
        "or ask me to replace the entry/exit rules with SMA."
    )


def test_generate_strategy_builder_follow_up_changes_exit_group_operator(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["exit_rule"] = {
        "kind": "group",
        "operator": "OR",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 70,
            },
            {
                "kind": "not",
                "rule": {
                    "kind": "atomic",
                    "type": "sma_above",
                    "symbol": "QQQ",
                    "fast_window": 1,
                    "slow_window": 200,
                },
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit from OR to AND",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"
    assert body["config"]["exit_rule"]["operator"] == "AND"


def test_generate_strategy_builder_mixed_composite_operator_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy. "
                "Buy when RSI is below 30 and MACD or SPY is above its 200 day SMA. "
                "Sell when RSI is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "could not deterministically parse" in body["message"].lower()


def test_generate_strategy_builder_draft_returns_valid_strategy_v2_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a mean reversion strategy for QQQ from 2019-01-02 to 2024-12-31 "
                "with 10% stop loss"
            ),
        },
    )

    assert response.status_code == 200

    body = response.json()
    config = body["config"]

    assert config["schema_version"] == "2.0"
    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "QQQ"
    assert config["start_date"] == "2019-01-02"
    assert config["end_date"] == "2024-12-31"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["risk"]["stop_loss_pct"] == 0.1
    assert config["core_overlay"]["enabled"] is False
    assert config["core_overlay"]["core_allocation_pct"] == 0.0
    assert config["allocation"]["entry_value"] == 1.0
    assert config["allocation"]["max_position_pct"] == 1.0


def test_generate_strategy_builder_draft_accepts_optional_context(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a moving average strategy for SPY",
            "context": {
                "strategy_id": "11111111-1111-1111-1111-111111111111",
                "base_version_id": "22222222-2222-2222-2222-222222222222",
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "old-config",
                },
            },
        },
    )

    assert response.status_code == 200

    body = response.json()
    config = body["config"]
    assert config["schema_version"] == "2.0"
    assert config["tradable_symbol"] == "SPY"
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["exit_rule"]["type"] == "sma_cross_below"


def test_generate_strategy_builder_draft_excludes_unused_null_fields(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a mean reversion strategy for QQQ",
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert "fast_window" not in config["entry_rule"]
    assert "slow_window" not in config["entry_rule"]
    assert "reference_symbol" not in config["entry_rule"]
    assert "month_values" not in config["entry_rule"]


def test_generate_strategy_builder_draft_parses_benchmark_take_profit_capital_and_cooldown(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with benchmark SPY, start with 250000, "
                "take profit at 15%, and cooldown 5 bars"
            ),
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["initial_capital"] == 250000.0
    assert config["risk"]["take_profit_pct"] == 0.15
    assert config["risk"]["cooldown_bars"] == 5


def test_generate_strategy_builder_draft_parses_partial_take_profit_position_management_and_core_allocation(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with partial take profit at 10% sell 50% max 2 times, "
                "scale in to 25%, scale out to 50%, profit reduce threshold to 5%, "
                "and core allocation at 60%"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["risk"]["partial_take_profit"]["trigger_profit_pct"] == 0.10
    assert config["risk"]["partial_take_profit"]["sell_fraction_of_position"] == 0.50
    assert config["risk"]["partial_take_profit"]["max_triggers"] == 2

    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["scale_out_fraction"] == 0.50
    assert config["position_management"]["profit_reduce_threshold"] == 0.05

    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.60

    assert "take_profit_pct" not in config["risk"]


def test_generate_strategy_builder_draft_parses_core_overlay_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2018-01-02 to 2026-04-24.\n"
                "Core overlay enabled.\n"
                "Core allocation 60%.\n"
                "Overlay allocation 40%.\n"
                "Core: Always hold QQQ.\n"
                "Overlay: Buy QQQ when RSI 14 is below 30.\n"
                "Sell QQQ when RSI 14 is above 70.\n"
                "Benchmark QQQ.\n"
                "Initial capital 100000.\n"
                "Transaction cost 5 bps."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert "could not convert string to float" not in body["message"]
    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.60
    assert config["allocation"]["entry_value"] == 0.40
    assert config["allocation"]["max_position_pct"] == 0.40
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70.0,
    }
    assert "Core allocation set to 60.0%." in body["summary"]
    assert "Overlay allocation set to 40.0%." in body["summary"]


def test_generate_strategy_builder_draft_parses_core_overlay_natural_language_prompt(client):
    prompt = (
        "Create a QQQ core-overlay strategy from 2018-01-02 to 2026-04-24. "
        "Use 60% always-invested core allocation in QQQ. "
        "Use the remaining 40% as a tactical overlay:\n"
        "- Enter the overlay when QQQ RSI(14) falls below 30\n"
        "- Exit the overlay when QQQ RSI(14) rises above 70\n"
        "Use QQQ as the benchmark, $100,000 initial capital, and 5 bps transaction cost."
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert "could not convert string to float" not in body["message"]
    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "QQQ"
    assert config["start_date"] == "2018-01-02"
    assert config["end_date"] == "2026-04-24"
    assert config["initial_capital"] == 100000.0
    assert config["transaction_cost_bps"] == 5.0
    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.60
    assert config["allocation"]["entry_value"] == 0.40
    assert config["allocation"]["max_position_pct"] == 0.40
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70.0,
    }


def test_generate_strategy_builder_draft_parses_transaction_cost_and_max_position(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for QQQ with transaction cost at 12 bps and max position at 40%",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["transaction_cost_bps"] == 12.0
    assert config["allocation"]["max_position_pct"] == 0.40


def test_generate_strategy_builder_draft_parses_custom_moving_average_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a moving average strategy for SPY using 10-day SMA crosses above 30-day SMA",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["entry_rule"]["fast_window"] == 10
    assert config["entry_rule"]["slow_window"] == 30
    assert config["exit_rule"]["fast_window"] == 10
    assert config["exit_rule"]["slow_window"] == 30
    assert "SPY 10-day SMA crosses above SPY 30-day SMA" in body["summary"]
    assert "SPY price is above its 30-day SMA" not in body["summary"]


def test_generate_strategy_builder_draft_parses_sma_above_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a 20/50 SMA above strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "sma_above"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["fast_window"] == 20
    assert config["entry_rule"]["slow_window"] == 50

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "sma_above"
    assert config["exit_rule"]["rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["rule"]["fast_window"] == 20
    assert config["exit_rule"]["rule"]["slow_window"] == 50


def test_generate_strategy_builder_draft_parses_macd_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a MACD strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "macd_bullish_cross"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"


def test_generate_strategy_builder_draft_parses_kd_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a KD strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["type"] == "kd_dead_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"


def test_generate_strategy_builder_draft_parses_stochastic_strategy_as_kd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a stochastic strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["type"] == "kd_dead_cross"


def test_generate_strategy_builder_draft_parses_seasonality_strategy_single_month(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a seasonality strategy for QQQ in November",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "month_in"
    assert config["entry_rule"]["month_values"] == [11]
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "month_in"
    assert config["exit_rule"]["rule"]["month_values"] == [11]


def test_generate_strategy_builder_draft_parses_seasonality_strategy_multiple_months(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a month strategy for SPY in November and December",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "SPY"
    assert config["entry_rule"]["type"] == "month_in"
    assert config["entry_rule"]["month_values"] == [11, 12]
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "month_in"
    assert config["exit_rule"]["rule"]["month_values"] == [11, 12]


def test_generate_strategy_builder_draft_parses_relative_strength_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a relative strength strategy for QQQ versus SPY over 20 days with 3% threshold",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "relative_return_above"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["reference_symbol"] == "SPY"
    assert config["entry_rule"]["lookback"] == 20
    assert config["entry_rule"]["threshold"] == 0.03
    assert "SPY" in config["reference_symbols"]

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "relative_return_above"
    assert config["exit_rule"]["rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["rule"]["reference_symbol"] == "SPY"
    assert config["exit_rule"]["rule"]["lookback"] == 20
    assert config["exit_rule"]["rule"]["threshold"] == 0.03
    assert (
        "Enter when QQQ outperforms SPY by more than 3.0% over 20 trading days."
        in body["summary"]
    )
    assert (
        "Exit when QQQ no longer outperforms SPY by more than 3.0% over 20 trading days."
        in body["summary"]
    )
    assert (
        "Interpreted relative strength language as QQQ outperforming SPY over 20 trading days."
        in body["assumptions"]
    )

    dates = pd.date_range("2021-01-04", periods=21, freq="B")

    def frame(symbol: str, closes: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": dates,
                "symbol": symbol,
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [1_000_000.0] * len(closes),
                "vwap": closes,
                "transactions": [1_000.0] * len(closes),
            }
        )

    strategy = StrategyV2.model_validate(config)
    bundle = MarketDataBundle(
        tradable=frame("QQQ", [100.0] * 20 + [108.0]),
        references={"SPY": frame("SPY", [100.0] * 20 + [104.0])},
    )
    enriched = enrich_market_data(bundle, strategy)

    assert evaluate_rule(strategy.entry_rule, enriched, 20, strategy.tradable_symbol) is True


def test_generate_strategy_builder_draft_parses_realized_volatility_below_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Buy QQQ when 20-day volatility is below 25%.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "realized_volatility_below"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["lookback"] == 20
    assert config["entry_rule"]["threshold"] == 0.25
    assert "Enter when QQQ 20-day realized volatility is below 25.0%." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_parses_realized_volatility_above_with_default_lookback(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Sell when volatility is above 35%.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"]["type"] == "realized_volatility_above"
    assert config["exit_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["lookback"] == 20
    assert config["exit_rule"]["threshold"] == 0.35
    assert "Used 20 trading days as the realized volatility lookback by default." in body["assumptions"]
    assert "Exit when QQQ 20-day realized volatility is above 35.0%." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_parses_composite_rsi_and_volatility_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy that buys when RSI is below 30 and 20-day volatility is below 25%. "
                "Sell when RSI is above 70 or 20-day volatility is above 35%."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "realized_volatility_below"
    assert config["entry_rule"]["rules"][1]["lookback"] == 20
    assert config["entry_rule"]["rules"][1]["threshold"] == 0.25
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1]["type"] == "realized_volatility_above"
    assert config["exit_rule"]["rules"][1]["lookback"] == 20
    assert config["exit_rule"]["rules"][1]["threshold"] == 0.35
    assert "QQQ 20-day realized volatility is below 25.0%" in body["summary"]
    assert "QQQ 20-day realized volatility is above 35.0%" in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_exact_realized_volatility_prompt_validates(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy that buys when 20-day volatility is below 25%. "
                "Sell when 20-day volatility is above 35%."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "realized_volatility_below",
        "symbol": "QQQ",
        "lookback": 20,
        "threshold": 0.25,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "realized_volatility_above",
        "symbol": "QQQ",
        "lookback": 20,
        "threshold": 0.35,
    }
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_syncs_reference_symbols_for_relative_strength_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a relative strength strategy for QQQ versus TLT over 60 days with 5% threshold",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["reference_symbols"] == ["TLT"]


def test_generate_strategy_builder_draft_parses_composite_entry_and_exit_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when RSI below 30 and MACD "
                "and exit when RSI above 70 or MACD"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert len(config["entry_rule"]["rules"]) == 2
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert len(config["exit_rule"]["rules"]) == 2
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_parses_composite_rule_with_sma_above_clause(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when 20 day SMA is above 50 day SMA and MACD "
                "and exit when RSI above 70"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "sma_above"
    assert config["entry_rule"]["rules"][0]["fast_window"] == 20
    assert config["entry_rule"]["rules"][0]["slow_window"] == 50
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_parses_window_entry_and_exit_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when any RSI below 30 within 5 bars "
                "and exit when all RSI above 70 within 3 bars"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["mode"] == "ANY"
    assert config["entry_rule"]["window_bars"] == 5
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["rule"]["threshold"] == 30

    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["mode"] == "ALL"
    assert config["exit_rule"]["window_bars"] == 3
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["rule"]["threshold"] == 70


def test_generate_strategy_builder_draft_parses_sequence_entry_and_exit_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when RSI below 30 then MACD within 5 bars "
                "and exit when RSI above 70 then MACD within 4 bars"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["window_bars"] == 5
    assert len(config["entry_rule"]["steps"]) == 2
    assert config["entry_rule"]["steps"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["steps"][0]["threshold"] == 30
    assert config["entry_rule"]["steps"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "sequence"
    assert config["exit_rule"]["window_bars"] == 4
    assert len(config["exit_rule"]["steps"]) == 2
    assert config["exit_rule"]["steps"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["steps"][0]["threshold"] == 70
    assert config["exit_rule"]["steps"][1]["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_parses_using_symbol_as_benchmark_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for QQQ using TLT as benchmark",
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "TLT"


def test_generate_strategy_builder_draft_uses_current_config_as_base_for_new_version(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Tighten stop loss to 8% and change benchmark to SPY",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-below-to-rsi-above",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.1,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["start_date"] == "2019-01-02"
    assert config["end_date"] == "2024-12-31"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_applies_sequential_rsi_entry_edit_from_current_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change RSI entry to 25",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                    "position_management": {
                        "scale_in_fraction": 0.25,
                        "scale_out_fraction": 0.5,
                        "profit_reduce_threshold": 0.05,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["threshold"] == 25
    assert config["exit_rule"]["threshold"] == 70
    assert "Updated RSI entry threshold from 30 to 25." in body["changes"]
    assert not any("3000.0%" in change or "2500.0%" in change for change in body["changes"])
    assert not any("relative strength threshold" in change for change in body["changes"])


@pytest.mark.parametrize(
    "prompt",
    [
        "change entry threshold to 25",
        "change the entry threshold to 25",
        "set entry threshold to 25",
        "update entry threshold to 25",
    ],
)
def test_generate_strategy_builder_draft_applies_plain_entry_threshold_edit_from_current_config(client, prompt):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_rsi_core_overlay_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 25,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70,
    }
    assert config["allocation"] == {
        "entry_mode": "percent_of_equity",
        "entry_value": 0.4,
        "max_position_pct": 0.4,
    }
    assert config["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.6,
    }
    assert "Updated RSI entry threshold from 30 to 25." in body["changes"]
    assert "Unsupported edit type" not in body["message"]


def test_generate_strategy_builder_draft_applies_sequential_rsi_exit_edit_from_current_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change RSI exit to 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                    "position_management": {
                        "scale_in_fraction": 0.25,
                        "scale_out_fraction": 0.5,
                        "profit_reduce_threshold": 0.05,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08
    assert config["entry_rule"]["threshold"] == 30
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["threshold"] == 65


@pytest.mark.parametrize(
    "prompt",
    [
        "change exit threshold to 65",
        "set exit threshold to 65",
    ],
)
def test_generate_strategy_builder_draft_applies_plain_exit_threshold_edit_from_current_config(client, prompt):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_rsi_core_overlay_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 65,
    }
    assert config["allocation"] == {
        "entry_mode": "percent_of_equity",
        "entry_value": 0.4,
        "max_position_pct": 0.4,
    }
    assert config["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.6,
    }
    assert "Updated RSI exit threshold from 70 to 65." in body["changes"]
    assert "Unsupported edit type" not in body["message"]


def test_generate_strategy_builder_draft_switches_existing_strategy_to_macd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "macd_bullish_cross"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_changes_tradable_symbol_and_rewrites_atomic_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change tradable symbol to SPY",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["tradable_symbol"] == "SPY"
    assert config["benchmark_symbol"] == "SPY"
    assert config["entry_rule"]["symbol"] == "SPY"
    assert config["exit_rule"]["symbol"] == "SPY"
    assert config["name"].startswith("spy-")
    assert "Updated tradable symbol from QQQ to SPY." in body["changes"]


def test_generate_strategy_builder_draft_switches_existing_strategy_to_sma_above(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to 10/30 SMA above",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "sma_above"
    assert config["entry_rule"]["fast_window"] == 10
    assert config["entry_rule"]["slow_window"] == 30

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "sma_above"
    assert config["exit_rule"]["rule"]["fast_window"] == 10
    assert config["exit_rule"]["rule"]["slow_window"] == 30


def test_generate_strategy_builder_draft_switches_existing_strategy_to_kd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["type"] == "kd_dead_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_switches_existing_strategy_to_seasonality(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to seasonality in November",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "month_in"
    assert config["entry_rule"]["month_values"] == [11]
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "month_in"
    assert config["exit_rule"]["rule"]["month_values"] == [11]
    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_switches_existing_strategy_to_relative_strength(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to relative strength versus SPY over 20 days with 3% threshold",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "relative_return_above"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["reference_symbol"] == "SPY"
    assert config["entry_rule"]["lookback"] == 20
    assert config["entry_rule"]["threshold"] == 0.03

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "relative_return_above"
    assert config["exit_rule"]["rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["rule"]["reference_symbol"] == "SPY"
    assert config["exit_rule"]["rule"]["lookback"] == 20
    assert config["exit_rule"]["rule"]["threshold"] == 0.03

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_switches_existing_strategy_to_composite_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "change this strategy to entry when RSI below 25 and MACD "
                "and exit when RSI above 65 or MACD"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][0]["threshold"] == 25
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][0]["threshold"] == 65
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08
    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_updates_entry_group_operator(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry group operator to or",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "OR"
    assert config["exit_rule"]["operator"] == "OR"
    assert "Updated entry group operator from AND to OR." in body["changes"]


def test_generate_strategy_builder_draft_updates_entry_group_second_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second condition of entry group to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "kd_golden_cross"
    assert "Updated entry group second condition" in " ".join(body["changes"])


def test_generate_strategy_builder_draft_updates_exit_group_first_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change first condition of exit group to RSI above 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][0]["threshold"] == 65
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"
    assert "Updated exit group first condition" in " ".join(body["changes"])


def test_generate_strategy_builder_draft_removes_second_condition_of_entry_group(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove second condition of entry group",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "group"
    assert any("Updated entry rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_first_condition_of_exit_group(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove first condition of exit group",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["kind"] == "group"
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_switches_existing_strategy_to_window_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "change this strategy to entry when any RSI below 25 within 5 bars "
                "and exit when all RSI above 65 within 3 bars"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["mode"] == "ANY"
    assert config["entry_rule"]["window_bars"] == 5
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["rule"]["threshold"] == 25

    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["mode"] == "ALL"
    assert config["exit_rule"]["window_bars"] == 3
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["rule"]["threshold"] == 65

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_updates_entry_window_bars_and_mode(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry window to 10 bars and change entry window mode to all",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["window_bars"] == 10
    assert config["entry_rule"]["mode"] == "ALL"
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"

    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["window_bars"] == 3
    assert config["exit_rule"]["mode"] == "ALL"

    assert "Updated entry window bars from 5 to 10." in body["changes"]
    assert "Updated entry window mode from ANY to ALL." in body["changes"]


def test_generate_strategy_builder_draft_updates_exit_window_bars(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit window to 6 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["window_bars"] == 6
    assert config["exit_rule"]["mode"] == "ALL"
    assert "Updated exit window bars from 3 to 6." in body["changes"]


def test_generate_strategy_builder_draft_updates_entry_window_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry window inner rule to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert "Updated entry window inner rule" in " ".join(body["changes"])


def test_generate_strategy_builder_draft_updates_exit_not_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit not inner rule to RSI above 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "sma_above",
                            "symbol": "QQQ",
                            "fast_window": 20,
                            "slow_window": 50,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["rule"]["threshold"] == 65
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_exit_not_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove exit not wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "sma_above",
                            "symbol": "QQQ",
                            "fast_window": 20,
                            "slow_window": 50,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "sma_above"
    assert config["exit_rule"]["fast_window"] == 20
    assert config["exit_rule"]["slow_window"] == 50
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_entry_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove entry window wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "window"
    assert any("Updated entry rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_switches_existing_strategy_to_sequence_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "change this strategy to entry when RSI below 25 then MACD within 5 bars "
                "and exit when RSI above 65 then MACD within 4 bars"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["window_bars"] == 5
    assert config["entry_rule"]["steps"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["steps"][0]["threshold"] == 25
    assert config["entry_rule"]["steps"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "sequence"
    assert config["exit_rule"]["window_bars"] == 4
    assert config["exit_rule"]["steps"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["steps"][0]["threshold"] == 65
    assert config["exit_rule"]["steps"][1]["type"] == "macd_bearish_cross"

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_updates_entry_sequence_bars(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry sequence to 8 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["window_bars"] == 8
    assert config["entry_rule"]["steps"][1]["type"] == "macd_bullish_cross"
    assert "Updated entry sequence bars from 5 to 8." in body["changes"]


def test_generate_strategy_builder_draft_updates_entry_sequence_second_step_to_kd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second step of entry sequence to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["steps"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["steps"][1]["type"] == "kd_golden_cross"
    assert "Updated entry sequence second step from macd_bullish_cross|symbol=QQQ to kd_golden_cross|symbol=QQQ." in body["changes"]


def test_generate_strategy_builder_draft_removes_second_step_of_entry_sequence(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove second step of entry sequence",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "sequence"
    assert any("Updated entry rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_first_step_of_exit_sequence(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove first step of exit sequence",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["kind"] == "sequence"
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_changes_tradable_symbol_and_rewrites_nested_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to IWM",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bullish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["tradable_symbol"] == "IWM"
    assert config["benchmark_symbol"] == "SPY"

    entry_group_rules = config["entry_rule"]["rule"]["rules"]
    assert entry_group_rules[0]["symbol"] == "IWM"
    assert entry_group_rules[1]["symbol"] == "IWM"

    exit_steps = config["exit_rule"]["steps"]
    assert exit_steps[0]["symbol"] == "IWM"
    assert exit_steps[1]["symbol"] == "IWM"

    assert "Updated tradable symbol from QQQ to IWM." in body["changes"]


def test_generate_strategy_builder_draft_updates_nested_relative_strength_rule_and_syncs_reference_symbols(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength reference to TLT and set relative strength threshold to 5%",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": ["GLD"],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "relative_return_above",
                                "symbol": "QQQ",
                                "reference_symbol": "GLD",
                                "lookback": 20,
                                "threshold": 0.03,
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "relative_return_above",
                                "symbol": "QQQ",
                                "reference_symbol": "GLD",
                                "lookback": 20,
                                "threshold": 0.03,
                            },
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    entry_relative_rule = config["entry_rule"]["rules"][1]
    exit_relative_rule = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert entry_relative_rule["reference_symbol"] == "TLT"
    assert entry_relative_rule["threshold"] == 0.05
    assert exit_relative_rule["reference_symbol"] == "TLT"
    assert exit_relative_rule["threshold"] == 0.05
    assert config["reference_symbols"] == ["TLT"]


def test_generate_strategy_builder_draft_adds_macd_confirmation_to_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert len(config["entry_rule"]["rules"]) == 2
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "AND"
    assert len(config["exit_rule"]["rules"]) == 2
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_macd_confirmation_from_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-with-macd-confirmation",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["threshold"] == 30

    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["threshold"] == 70

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_adds_kd_confirmation_to_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add KD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][1]["type"] == "kd_golden_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["rules"][1]["type"] == "kd_dead_cross"


def test_generate_strategy_builder_draft_adds_relative_strength_confirmation_to_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add relative strength confirmation versus TLT over 60 days with 5% threshold",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][1]["type"] == "relative_return_above"
    assert config["entry_rule"]["rules"][1]["reference_symbol"] == "TLT"
    assert config["entry_rule"]["rules"][1]["lookback"] == 60
    assert config["entry_rule"]["rules"][1]["threshold"] == 0.05

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["rules"][1]["type"] == "relative_return_above"
    assert config["exit_rule"]["rules"][1]["reference_symbol"] == "TLT"
    assert config["exit_rule"]["rules"][1]["lookback"] == 60
    assert config["exit_rule"]["rules"][1]["threshold"] == 0.05


def test_generate_strategy_builder_draft_updates_seasonality_months_and_records_change(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change months to January and February",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-month-in-to-not-month-in",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "month_in",
                        "month_values": [11],
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "month_in",
                            "month_values": [11],
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["month_values"] == [1, 2]
    assert config["exit_rule"]["rule"]["month_values"] == [1, 2]
    assert "Updated seasonality months from 11 to 1, 2." in body["changes"]


def test_generate_strategy_builder_draft_updates_relative_strength_reference_symbol(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength reference to TLT",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "QQQ",
                        "reference_symbol": "SPY",
                        "lookback": 20,
                        "threshold": 0.03,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "relative_return_above",
                            "symbol": "QQQ",
                            "reference_symbol": "SPY",
                            "lookback": 20,
                            "threshold": 0.03,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["reference_symbol"] == "TLT"
    assert config["exit_rule"]["rule"]["reference_symbol"] == "TLT"
    assert "Updated relative strength reference symbol from SPY to TLT." in body["changes"]


def test_generate_strategy_builder_draft_updates_relative_strength_lookback(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength lookback to 60",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "QQQ",
                        "reference_symbol": "SPY",
                        "lookback": 20,
                        "threshold": 0.03,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "relative_return_above",
                            "symbol": "QQQ",
                            "reference_symbol": "SPY",
                            "lookback": 20,
                            "threshold": 0.03,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["lookback"] == 60
    assert config["exit_rule"]["rule"]["lookback"] == 60
    assert "Updated relative strength lookback from 20 to 60." in body["changes"]


def test_generate_strategy_builder_draft_updates_relative_strength_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength threshold to 5%",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "QQQ",
                        "reference_symbol": "SPY",
                        "lookback": 20,
                        "threshold": 0.03,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "relative_return_above",
                            "symbol": "QQQ",
                            "reference_symbol": "SPY",
                            "lookback": 20,
                            "threshold": 0.03,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["threshold"] == 0.05
    assert config["exit_rule"]["rule"]["threshold"] == 0.05
    assert "Updated relative strength threshold from 3.0% to 5.0%." in body["changes"]


def test_generate_strategy_builder_draft_applies_sequential_stop_loss_take_profit_allocation_benchmark_and_cooldown_edits(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change stop loss to 6%, change take profit to 18%, change allocation to 40%, change benchmark to TLT, and change cooldown to 3 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "take_profit_pct": 0.12,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["benchmark_symbol"] == "TLT"
    assert config["allocation"]["entry_value"] == 0.4
    assert config["risk"]["stop_loss_pct"] == 0.06
    assert config["risk"]["take_profit_pct"] == 0.18
    assert config["risk"]["cooldown_bars"] == 3
    assert "Updated stop loss from 8.0% to 6.0%." in body["changes"]
    assert "Updated take profit from 12.0% to 18.0%." in body["changes"]
    assert "Updated allocation from 100.0% to 40.0%." in body["changes"]
    assert "Updated benchmark from SPY to TLT." in body["changes"]
    assert "Updated cooldown bars from 0 to 3." in body["changes"]



def test_generate_strategy_builder_draft_can_remove_stop_loss_take_profit_and_cooldown(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove stop loss, remove take profit, and remove cooldown",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "take_profit_pct": 0.15,
                        "cooldown_bars": 5,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert "stop_loss_pct" not in config["risk"]
    assert "take_profit_pct" not in config["risk"]
    assert config["risk"]["cooldown_bars"] == 0
    assert "Updated stop loss from 8.0% to none." in body["changes"]
    assert "Updated take profit from 15.0% to none." in body["changes"]
    assert "Updated cooldown bars from 5 to 0." in body["changes"]


def test_generate_strategy_builder_draft_updates_partial_take_profit_position_management_and_core_allocation(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "add partial take profit at 12% sell 40% max 3 times, "
                "set scale in to 30%, set scale out to 60%, "
                "set profit reduce threshold to 7%, and enable core allocation at 55%"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                    "position_management": None,
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["risk"]["partial_take_profit"]["trigger_profit_pct"] == 0.12
    assert config["risk"]["partial_take_profit"]["sell_fraction_of_position"] == 0.40
    assert config["risk"]["partial_take_profit"]["max_triggers"] == 3

    assert config["position_management"]["scale_in_fraction"] == 0.30
    assert config["position_management"]["scale_out_fraction"] == 0.60
    assert config["position_management"]["profit_reduce_threshold"] == 0.07

    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.55

    assert "Updated partial take profit trigger from none to 12.0%." in body["changes"]
    assert "Updated scale in fraction from none to 30.0%." in body["changes"]
    assert "Updated core allocation from disabled to enabled." in body["changes"]


def test_generate_strategy_builder_draft_updates_transaction_cost_and_max_position(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change transaction cost to 9 bps and set max position to 35%",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["transaction_cost_bps"] == 9.0
    assert config["allocation"]["max_position_pct"] == 0.35
    assert "Updated transaction cost from 5 to 9.0." in body["changes"]
    assert "Updated max position from 100.0% to 35.0%." in body["changes"]


def test_generate_strategy_builder_draft_can_remove_partial_take_profit_position_management_and_core_allocation(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove partial take profit, remove position management, and disable core allocation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-managed-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
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
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "partial_take_profit": {
                            "trigger_profit_pct": 0.10,
                            "sell_fraction_of_position": 0.50,
                            "max_triggers": 2,
                        },
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": True,
                        "core_allocation_pct": 0.60,
                    },
                    "position_management": {
                        "scale_in_fraction": 0.25,
                        "scale_out_fraction": 0.50,
                        "profit_reduce_threshold": 0.05,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert "partial_take_profit" not in config["risk"]
    assert "position_management" not in config or config["position_management"] is None
    assert config["core_overlay"]["enabled"] is False
    assert config["core_overlay"]["core_allocation_pct"] == 0.0

    assert "Updated partial take profit trigger from 10.0% to none." in body["changes"]
    assert "Updated scale in fraction from 25.0% to none." in body["changes"]
    assert "Updated core allocation from enabled to disabled." in body["changes"]


def test_generate_strategy_builder_returns_answer_for_info_question(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What ETF symbols are currently supported?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert "Supported ETF symbols" in body["message"]


def test_generate_strategy_builder_returns_validation_error_for_over_limit_date_edit(
    client,
    db_session,
):
    plan = db_session.query(Plan).filter(Plan.code == "TEST_PRO").one()
    plan.max_backtest_years = 3
    db_session.commit()
    db_session.refresh(plan)
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change start date to 2020-01-01",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "plan limit" in body["message"]


def test_generate_strategy_builder_returns_validation_error_for_confirmation_without_current_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert "existing draft" in body["message"]
    assert "confirmation" in body["message"]


def test_generate_strategy_builder_draft_uses_symbol_history_aware_default_window_for_long_history(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2010, 1, 1), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a mean reversion strategy for QQQ"},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["end_date"] == "2026-04-17"
    assert config["start_date"] == "2018-01-02"


def test_generate_strategy_builder_draft_shortens_default_window_for_newer_symbol_history(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT"},
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "IBIT"
    assert config["start_date"] == "2024-01-11"
    assert config["end_date"] == "2026-04-17"


def test_generate_strategy_builder_draft_preserves_explicit_dates_even_with_symbol_history(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT from 2025-01-01 to 2026-03-01"},
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["start_date"] == "2025-01-01"
    assert config["end_date"] == "2026-03-01"


def test_generate_strategy_builder_draft_falls_back_when_metadata_is_missing(
    client,
    monkeypatch,
):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a mean reversion strategy for QQQ"},
    )

    assert response.status_code == 200
    config = response.json()["config"]
    settings = get_settings()

    assert config["tradable_symbol"] == "QQQ"
    assert config["start_date"] == settings.supported_data_start.isoformat()
    assert config["end_date"] == settings.supported_data_end.isoformat()


def test_generate_strategy_builder_draft_returns_assumptions_in_response(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "CREATE_DRAFT"
    assert any(
        "Used available history for IBIT starting on 2024-01-11." in item
        for item in body["assumptions"]
    )
    assert any(
        "Used the default backtest range 2024-01-11 to 2026-04-17." in item
        for item in body["assumptions"]
    )


def test_generate_strategy_builder_summary_mentions_available_history_when_metadata_shortens_window(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT"},
    )

    assert response.status_code == 200
    body = response.json()

    assert "using available history" in body["summary"]
    assert "from 2024-01-11 to 2026-04-17" in body["summary"]
    assert "from 2024-01-11 to 2026-04-17. Enter when" in body["summary"]


def test_generate_strategy_builder_summary_mentions_default_platform_range_when_metadata_is_missing(
    client,
    monkeypatch,
):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a mean reversion strategy for QQQ"},
    )

    assert response.status_code == 200
    body = response.json()

    assert "using the default platform range" in body["summary"]


def test_generate_strategy_builder_returns_friendlier_unsupported_symbol_message(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for AAPL"},
    )

    assert response.status_code == 400
    assert "not supported yet" in response.json()["detail"]
    assert "ETF-first" in response.json()["detail"]


def test_generate_strategy_builder_returns_friendlier_plan_limit_message(
    client,
    db_session,
):
    plan = db_session.query(Plan).filter(Plan.code == "TEST_PRO").one()
    plan.max_backtest_years = 5
    db_session.commit()
    db_session.refresh(plan)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for QQQ from 2018-01-02 to 2026-04-14",
        },
    )

    assert response.status_code == 400
    assert "current plan limit" in response.json()["detail"]
    assert "shorten the range" in response.json()["detail"]


def test_generate_strategy_builder_returns_validation_error_for_unsupported_edit_type(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add bollinger bands confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert "not supported yet" in body["message"]
    assert "benchmark" in body["message"]


def test_generate_strategy_builder_returns_structured_supported_symbols_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What ETFs are available?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_SYMBOLS"
    assert "QQQ" in body["answer_data"]["supported_symbols"]
    assert "SPY" in body["message"]


def test_generate_strategy_builder_returns_symbol_data_coverage_answer(client, monkeypatch):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_response,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2010, 1, 4), date(2026, 4, 24)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What date range is available for QQQ?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "DATA_COVERAGE"
    assert body["answer_data"]["supported_symbols"] == ["QQQ"]
    assert body["answer_data"]["supported_data_start"] == "2010-01-04"
    assert body["answer_data"]["supported_data_end"] == "2026-04-24"
    assert body["answer_data"]["max_backtest_years"] is not None
    assert "QQQ coverage is available" in body["message"]


def test_generate_strategy_builder_returns_data_coverage_fallback_when_metadata_missing(
    client,
    monkeypatch,
):
    monkeypatch.setattr(builder_response, "get_etf_history_range", lambda symbol: None)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What date range is available for QQQ?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "DATA_COVERAGE"
    assert body["answer_data"]["supported_symbols"] == ["QQQ"]
    assert body["answer_data"]["supported_data_start"] is None
    assert "could not find coverage metadata for QQQ" in body["message"]


def test_generate_strategy_builder_returns_general_data_coverage_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What date range is supported?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "DATA_COVERAGE"
    assert body["answer_data"]["supported_data_start"] is not None
    assert body["answer_data"]["supported_data_end"] is not None
    assert body["answer_data"]["max_backtest_years"] is not None


def test_generate_strategy_builder_returns_unsupported_stock_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Can I test NVDA?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_SYMBOLS"
    assert "NVDA is not currently available" in body["message"]
    assert "ETF strategy research" in body["message"]
    assert "QQQ" in body["message"]
    assert "SPY" in body["message"]


def test_generate_strategy_builder_returns_benchmark_symbol_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Can I use SPY as benchmark?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_SYMBOLS"
    assert "SPY" in body["message"]
    assert "benchmark" in body["message"]


def test_generate_strategy_builder_returns_structured_plan_limits_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What are my plan limits?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["answer_data"]["answer_type"] == "PLAN_LIMITS"
    assert body["answer_data"]["max_backtest_years"] is not None


@pytest.mark.parametrize(
    "prompt",
    [
        "What strategies can I build?",
        "What indicators are supported?",
        "What can I ask you to do?",
    ],
)
def test_generate_strategy_builder_returns_structured_supported_strategy_types_answer(client, prompt):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_STRATEGY_TYPES"
    assert body["message"] == (
        "You can currently build ETF strategies using RSI mean reversion, SMA / moving-average crossover, "
        "SMA trend-state rules, MACD, KD / stochastic, relative strength, VIX and rates filters, "
        "yield-curve filters, realized volatility, seasonality, stop loss, take profit, cooldown, "
        "benchmark comparison, and core-overlay allocation."
    )
    assert "RSI mean reversion" in body["message"]
    assert "SMA / moving-average crossover" in body["message"]
    assert "SMA trend-state rules" in body["message"]
    assert "MACD" in body["message"]
    assert "KD" in body["message"]
    assert "relative strength" in body["message"]
    assert "VIX and rates filters" in body["message"]
    assert "yield-curve filters" in body["message"]
    assert "seasonality" in body["message"]
    assert "stop loss" in body["message"]
    assert "take profit" in body["message"]
    assert "cooldown" in body["message"]
    assert "benchmark comparison" in body["message"]
    assert "core-overlay allocation" in body["message"]

    internal_terms = [
        "nested",
        "direct removal",
        "NOT wrapper",
        "sequence",
        "composite replacement",
        "parser",
        "window inner",
        "group operator",
        "confirmation filter",
    ]
    for term in internal_terms:
        assert term.lower() not in body["message"].lower()


def test_generate_strategy_builder_returns_structured_validation_data_for_unsupported_symbol(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for AAPL"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "not supported yet" in detail


def test_generate_strategy_builder_returns_structured_validation_error_for_unsupported_edit_type(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add bollinger bands confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["validation_data"]["validation_type"] == "UNSUPPORTED_EDIT"
    assert body["validation_data"]["suggested_action"] is not None
    assert "MACD" in body["validation_data"]["suggested_action"]
    assert "KD" in body["validation_data"]["suggested_action"]
    assert "seasonality" in body["validation_data"]["suggested_action"]
    assert "relative strength" in body["validation_data"]["suggested_action"]


def test_generate_strategy_builder_returns_guidance_data_for_no_change_response(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "tell me what this draft can do",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "ANSWER"
    assert body["guidance_data"]["guidance_type"] == "NO_CHANGE"
    assert len(body["guidance_data"]["suggested_actions"]) > 0
    assert "Change tradable symbol" in body["guidance_data"]["suggested_actions"]
    assert "Adjust max position" in body["guidance_data"]["suggested_actions"]
    assert "Change transaction cost" in body["guidance_data"]["suggested_actions"]
    assert "Adjust RSI thresholds" in body["guidance_data"]["suggested_actions"]
    assert "Edit nested RSI settings" in body["guidance_data"]["suggested_actions"]
    assert "Switch moving-average rules" in body["guidance_data"]["suggested_actions"]
    assert "Edit nested moving-average windows" in body["guidance_data"]["suggested_actions"]
    assert "Switch to MACD" in body["guidance_data"]["suggested_actions"]
    assert "Switch to KD / stochastic" in body["guidance_data"]["suggested_actions"]
    assert "Switch to seasonality by month" in body["guidance_data"]["suggested_actions"]
    assert "Edit seasonality months" in body["guidance_data"]["suggested_actions"]
    assert "Add / remove seasonality months" in body["guidance_data"]["suggested_actions"]
    assert "Switch to relative strength" in body["guidance_data"]["suggested_actions"]
    assert "Switch to SMA above" in body["guidance_data"]["suggested_actions"]
    assert "Edit nested relative strength settings" in body["guidance_data"]["suggested_actions"]
    assert "Add MACD confirmation" in body["guidance_data"]["suggested_actions"]
    assert "Add KD / stochastic confirmation" in body["guidance_data"]["suggested_actions"]
    assert "Add relative strength confirmation" in body["guidance_data"]["suggested_actions"]
    assert "Remove confirmation filters" in body["guidance_data"]["suggested_actions"]
    assert "Change window bars / mode" in body["guidance_data"]["suggested_actions"]
    assert "Change sequence bars / steps" in body["guidance_data"]["suggested_actions"]
    assert "Change group operator" in body["guidance_data"]["suggested_actions"]
    assert "Change group conditions" in body["guidance_data"]["suggested_actions"]
    assert "Change window inner rule" in body["guidance_data"]["suggested_actions"]
    assert "Adjust partial take profit" in body["guidance_data"]["suggested_actions"]
    assert "Adjust position management" in body["guidance_data"]["suggested_actions"]
    assert "Enable / disable core allocation" in body["guidance_data"]["suggested_actions"]
    assert "Change NOT inner rule" in body["guidance_data"]["suggested_actions"]
    assert "Remove NOT wrapper" in body["guidance_data"]["suggested_actions"]
    assert "Remove group conditions" in body["guidance_data"]["suggested_actions"]
    assert "Remove window wrapper" in body["guidance_data"]["suggested_actions"]
    assert "Remove sequence steps" in body["guidance_data"]["suggested_actions"]


def test_generate_strategy_builder_returns_guidance_data_for_unsupported_edit_target(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add bollinger bands confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["guidance_data"]["guidance_type"] == "UNSUPPORTED_EDIT_TARGET"
    assert len(body["guidance_data"]["suggested_actions"]) > 0


def test_generate_strategy_builder_updates_only_exit_sma_slow_window(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit rule slow window to 20",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 5
    assert config["entry_rule"]["slow_window"] == 10

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 5
    assert config["exit_rule"]["slow_window"] == 20


def test_generate_strategy_builder_does_not_replace_exit_rule_with_fallback_rsi_on_partial_exit_edit(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit rule slow window to 20",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["exit_rule"]["type"] != "rsi_above"
    assert config["exit_rule"]["symbol"] == "SPY"


def test_generate_strategy_builder_updates_only_entry_sma_fast_window_with_sma_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry SMA fast window to 8",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 8
    assert config["entry_rule"]["slow_window"] == 10

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 5
    assert config["exit_rule"]["slow_window"] == 10


def test_generate_strategy_builder_updates_only_entry_sma_slow_window_with_sma_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry SMA slow window to 21",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 5
    assert config["entry_rule"]["slow_window"] == 21

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 5
    assert config["exit_rule"]["slow_window"] == 10


def test_generate_strategy_builder_updates_only_exit_sma_fast_window_with_sma_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit SMA fast window to 7",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 5
    assert config["entry_rule"]["slow_window"] == 10

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 7
    assert config["exit_rule"]["slow_window"] == 10


def test_generate_strategy_builder_draft_defaults_position_management_to_none(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create an SMA crossover strategy for SPY"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "CREATE_DRAFT"
    config = body["config"]

    assert config["tradable_symbol"] == "SPY"
    assert config["allocation"]["entry_value"] == 1.0
    assert config["allocation"]["max_position_pct"] == 1.0
    assert config["core_overlay"]["enabled"] is False

    # Critical alignment check:
    # missing position_management should stay absent/null in generated drafts
    assert "position_management" not in config or config["position_management"] is None


def test_generate_strategy_builder_draft_updates_top_level_seasonality_months(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change seasonality months to March and April",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-seasonality-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "month_in",
                        "month_values": [1, 2, 3],
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "month_in",
                            "month_values": [1, 2, 3],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["month_values"] == [3, 4]
    assert config["exit_rule"]["rule"]["month_values"] == [3, 4]


def test_generate_strategy_builder_draft_adds_month_to_nested_seasonality_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add March to seasonality months",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-seasonality-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "month_in",
                                "month_values": [1, 2],
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["rules"][1]["month_values"] == [1, 2, 3]


def test_generate_strategy_builder_draft_removes_month_from_seasonality_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove February from seasonality months",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-seasonality-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "month_in",
                        "month_values": [1, 2, 3],
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "month_in",
                            "month_values": [1, 2, 3],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["month_values"] == [1, 3]
    assert config["exit_rule"]["rule"]["month_values"] == [1, 3]


def test_generate_strategy_builder_draft_updates_nested_entry_rsi_settings(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry rsi threshold to 25 and change entry rsi lookback to 10",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-entry-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_rsi = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_rsi["type"] == "rsi_below"
    assert nested_rsi["threshold"] == 25
    assert nested_rsi["lookback"] == 10
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_updates_nested_exit_rsi_settings(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit rsi threshold to 65 and change exit rsi lookback to 21",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-exit-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 70,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_rsi = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_rsi["type"] == "rsi_above"
    assert nested_rsi["threshold"] == 65
    assert nested_rsi["lookback"] == 21


def test_generate_strategy_builder_draft_updates_nested_entry_moving_average_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry fast window to 10 and change entry slow window to 40",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-entry-sma-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "type": "sma_cross_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_sma = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_sma["type"] == "sma_cross_above"
    assert nested_sma["fast_window"] == 10
    assert nested_sma["slow_window"] == 40
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_updates_nested_exit_moving_average_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit fast window to 15 and change exit slow window to 60",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-exit-sma-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_sma = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_sma["type"] == "sma_above"
    assert nested_sma["fast_window"] == 15
    assert nested_sma["slow_window"] == 60


def test_generate_strategy_builder_draft_removes_nested_macd_confirmation_from_entry_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-macd-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bullish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["rule"]["kind"] == "atomic"
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"


def test_generate_strategy_builder_draft_removes_nested_macd_confirmation_from_exit_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-macd-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_above",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 70,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bearish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"


def test_generate_strategy_builder_draft_updates_entry_group_condition_to_window_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change first condition of entry group to any RSI below 25 within 5 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_rule = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_rule["kind"] == "window"
    assert updated_rule["window_bars"] == 5
    assert updated_rule["mode"] == "ANY"
    assert updated_rule["rule"]["kind"] == "atomic"
    assert updated_rule["rule"]["type"] == "rsi_below"
    assert updated_rule["rule"]["threshold"] == 25


def test_generate_strategy_builder_draft_updates_exit_sequence_step_to_group_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second step of exit sequence to RSI above 70 and MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_step = config["exit_rule"]["steps"][1]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_step["kind"] == "group"
    assert updated_step["operator"] == "AND"
    assert updated_step["rules"][0]["type"] == "rsi_above"
    assert updated_step["rules"][0]["threshold"] == 70
    assert updated_step["rules"][1]["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_updates_nested_exit_not_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit not inner rule to RSI above 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_rule = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "not"
    assert nested_rule["kind"] == "atomic"
    assert nested_rule["type"] == "rsi_above"
    assert nested_rule["threshold"] == 65


def test_generate_strategy_builder_draft_removes_nested_exit_not_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove exit not wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert response.status_code == 200
    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "sma_above"
    assert config["exit_rule"]["rule"]["fast_window"] == 20
    assert config["exit_rule"]["rule"]["slow_window"] == 50


def test_generate_strategy_builder_draft_updates_nested_entry_group_operator(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry group operator to OR",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-group-operator-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bullish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["rule"]["kind"] == "group"
    assert config["entry_rule"]["rule"]["operator"] == "OR"


def test_generate_strategy_builder_draft_updates_nested_exit_group_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change first condition of exit group to all RSI above 75 within 4 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-group-condition-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_above",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 70,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bearish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_rule = config["exit_rule"]["rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_rule["kind"] == "window"
    assert updated_rule["window_bars"] == 4
    assert updated_rule["mode"] == "ALL"
    assert updated_rule["rule"]["kind"] == "atomic"
    assert updated_rule["rule"]["type"] == "rsi_above"
    assert updated_rule["rule"]["threshold"] == 75


def test_generate_strategy_builder_draft_updates_nested_entry_window_bars_and_mode(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry window to 6 bars and change entry window mode to all",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-window-edit-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "kind": "window",
                                "window_bars": 3,
                                "mode": "ANY",
                                "rule": {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_window = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_window["kind"] == "window"
    assert nested_window["window_bars"] == 6
    assert nested_window["mode"] == "ALL"


def test_generate_strategy_builder_draft_updates_nested_exit_window_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit window inner rule to MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-window-inner-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "window",
                            "window_bars": 3,
                            "mode": "ANY",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_window_rule = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["kind"] == "window"
    assert nested_window_rule["kind"] == "atomic"
    assert nested_window_rule["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_updates_nested_entry_sequence_step(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second step of entry sequence to RSI below 20 and MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-sequence-step-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "kind": "sequence",
                                "window_bars": 4,
                                "steps": [
                                    {
                                        "kind": "atomic",
                                        "type": "rsi_below",
                                        "symbol": "QQQ",
                                        "lookback": 14,
                                        "threshold": 30,
                                    },
                                    {
                                        "kind": "atomic",
                                        "type": "sma_cross_above",
                                        "symbol": "QQQ",
                                        "fast_window": 20,
                                        "slow_window": 50,
                                    },
                                ],
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_step = config["entry_rule"]["rules"][0]["steps"][1]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_step["kind"] == "group"
    assert updated_step["operator"] == "AND"
    assert updated_step["rules"][0]["type"] == "rsi_below"
    assert updated_step["rules"][0]["threshold"] == 20
    assert updated_step["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_removes_nested_exit_sequence_step(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove second step of exit sequence",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-sequence-remove-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "sequence",
                            "window_bars": 4,
                            "steps": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_above",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 70,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bearish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"


def test_generate_strategy_builder_draft_removes_nested_entry_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove entry window wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-window-remove-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
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
                                "kind": "window",
                                "window_bars": 3,
                                "mode": "ANY",
                                "rule": {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][0]["kind"] == "atomic"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"


def test_generate_strategy_builder_draft_adds_macd_confirmation_inside_entry_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-confirmation-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "symbol": "QQQ",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    inner_rule = config["entry_rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert inner_rule["kind"] == "group"
    assert inner_rule["operator"] == "AND"
    assert inner_rule["rules"][0]["type"] == "rsi_below"
    assert inner_rule["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_adds_macd_confirmation_inside_exit_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-confirmation-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "symbol": "QQQ",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    inner_rule = config["exit_rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert inner_rule["kind"] == "group"
    assert inner_rule["operator"] == "AND"
    assert inner_rule["rules"][0]["type"] == "rsi_above"
    assert inner_rule["rules"][1]["type"] == "macd_bearish_cross"
