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


def test_generate_strategy_builder_returns_validation_error_for_over_limit_date_edit(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change start date to 2018-01-01",
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