from __future__ import annotations

from datetime import date

import pytest
import market_simulator.services.strategy_builder_service as builder_service
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
    monkeypatch.setattr(builder_service, "get_etf_history_range", lambda symbol: None)


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
            "prompt": "Create a moving average strategy for SPY using 10 day SMA crosses above 30 day SMA",
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["entry_rule"]["fast_window"] == 10
    assert config["entry_rule"]["slow_window"] == 30
    assert config["exit_rule"]["fast_window"] == 10
    assert config["exit_rule"]["slow_window"] == 30


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

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "relative_return_above"
    assert config["exit_rule"]["rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["rule"]["reference_symbol"] == "SPY"
    assert config["exit_rule"]["rule"]["lookback"] == 20
    assert config["exit_rule"]["rule"]["threshold"] == 0.03


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
    config = response.json()["config"]

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["threshold"] == 25
    assert config["exit_rule"]["threshold"] == 70


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
        builder_service,
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
        builder_service,
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
        builder_service,
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
    monkeypatch.setattr(builder_service, "get_etf_history_range", lambda symbol: None)

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
        builder_service,
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
        builder_service,
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


def test_generate_strategy_builder_summary_mentions_default_platform_range_when_metadata_is_missing(
    client,
    monkeypatch,
):
    monkeypatch.setattr(builder_service, "get_etf_history_range", lambda symbol: None)

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
        json={"prompt": "What ETF symbols are currently supported?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["answer_data"]["answer_type"] == "SUPPORTED_SYMBOLS"
    assert "QQQ" in body["answer_data"]["supported_symbols"]


def test_generate_strategy_builder_returns_structured_data_coverage_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What date range is supported?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["answer_data"]["answer_type"] == "DATA_COVERAGE"
    assert body["answer_data"]["supported_data_start"] is not None
    assert body["answer_data"]["supported_data_end"] is not None
    assert body["answer_data"]["max_backtest_years"] is not None


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


def test_generate_strategy_builder_returns_structured_supported_strategy_types_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What strategy types or indicators are supported?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["answer_data"]["answer_type"] == "SUPPORTED_STRATEGY_TYPES"
    assert "MACD" in body["message"]
    assert "SMA-above" in body["message"]
    assert "nested RSI threshold/lookback edits" in body["message"]
    assert "KD" in body["message"]
    assert "seasonality" in body["message"]
    assert "seasonality month edits" in body["message"]
    assert "relative strength" in body["message"]
    assert "tradable symbol changes" in body["message"]
    assert "nested relative strength edits" in body["message"]
    assert "transaction cost" in body["message"]
    assert "max position percentage" in body["message"]
    assert "AND/OR" in body["message"]
    assert "within N bars" in body["message"]
    assert "NOT inner rules" in body["message"]
    assert "NOT wrappers" in body["message"]
    assert "then Y within N bars" in body["message"]
    assert "confirmation filters" in body["message"]
    assert "window bars/modes and sequence bars/steps" in body["message"]
    assert "group operators and group conditions" in body["message"]
    assert "partial take profit" in body["message"]
    assert "position management" in body["message"]
    assert "core allocation / core overlay" in body["message"]
    assert "removal of group conditions" in body["message"]
    assert "removal of window wrappers" in body["message"]
    assert "removal of sequence steps" in body["message"]


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