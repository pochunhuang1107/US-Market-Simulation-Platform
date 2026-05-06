from __future__ import annotations

import pytest

from market_simulator.services.draft_validation import (
    MINIMUM_TRADE_SELF_BLOCKING_WARNING,
    collect_draft_config_warnings,
    validate_draft_config,
)


def test_validate_draft_config_rejects_unsupported_nested_symbols():
    config = {
        "schema_version": "2.0",
        "name": "qqq-window-group-test",
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
                        "type": "relative_return_above",
                        "symbol": "QQQ",
                        "reference_symbol": "AAPL",
                        "lookback": 20,
                        "threshold": 0.03,
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
    }

    with pytest.raises(ValueError, match="AAPL is not supported yet"):
        validate_draft_config(
            config=config,
            max_backtest_years=5,
        )


def test_collect_draft_config_warnings_flags_self_blocking_minimum_trade_pct():
    config = {
        "schema_version": "2.0",
        "name": "qqq-minimum-trade-warning",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "QQQ",
        "reference_symbols": [],
        "start_date": "2021-04-14",
        "end_date": "2026-04-14",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 0.01,
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
        "position_management": {
            "minimum_trade_pct_of_equity": 0.01,
        },
    }

    assert collect_draft_config_warnings(config) == [MINIMUM_TRADE_SELF_BLOCKING_WARNING]
    assert validate_draft_config(config=config, max_backtest_years=5) == [
        MINIMUM_TRADE_SELF_BLOCKING_WARNING
    ]
