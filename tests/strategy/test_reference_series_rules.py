from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine import runner
from market_simulator.models.strategy_v2 import AtomicRule, StrategyV2
from market_simulator.strategy.evaluator import evaluate_rule


def _tradable(
    dates: list[str] | None = None,
    closes: list[float] | None = None,
) -> pd.DataFrame:
    dates = dates or ["2021-01-04", "2021-01-05", "2021-01-06"]
    closes = closes or [100.0 + index for index in range(len(dates))]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "symbol": ["QQQ"] * len(dates),
            "open": closes,
            "high": [close + 1.0 for close in closes],
            "low": [close - 1.0 for close in closes],
            "close": closes,
            "rsi_14": [60.0] + [40.0] * max(len(dates) - 1, 0),
        }
    )


def _bundle(
    *,
    reference_symbol: str = "VIX",
    reference_df: pd.DataFrame,
    dates: list[str] | None = None,
    closes: list[float] | None = None,
) -> MarketDataBundle:
    return MarketDataBundle(
        tradable=_tradable(dates, closes),
        references={reference_symbol: reference_df},
    )


def _reference_series(
    symbol: str,
    dates: list[str],
    values: list[float] | None = None,
    closes: list[float] | None = None,
) -> pd.DataFrame:
    data: dict[str, object] = {
        "date": pd.to_datetime(dates),
        "symbol": [symbol] * len(dates),
    }
    if values is not None:
        data["value"] = values
    if closes is not None:
        data["close"] = closes
    return pd.DataFrame(data)


def _strategy_config(
    entry_rule: dict,
    exit_rule: dict | None = None,
    position_management: dict | None = None,
) -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-reference-series-test",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "QQQ",
        "reference_symbols": ["VIX", "DGS10"],
        "start_date": "2021-01-04",
        "end_date": "2021-01-06",
        "initial_capital": 100000,
        "transaction_cost_bps": 0,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": entry_rule,
        "exit_rule": exit_rule
        or {
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
        "position_management": position_management,
    }


def test_series_rules_validate_in_strategy_v2() -> None:
    StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 25,
            }
        )
    )
    StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "atomic",
                "type": "series_above",
                "symbol": "DGS10",
                "threshold": 4.5,
            }
        )
    )


@pytest.mark.parametrize("missing_field", ["symbol", "threshold"])
def test_series_rules_require_symbol_and_threshold(missing_field: str) -> None:
    payload = {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 25,
    }
    payload.pop(missing_field)

    with pytest.raises(ValidationError, match=f"{missing_field} required"):
        AtomicRule.model_validate(payload)


def test_vix_series_below_uses_value_when_available() -> None:
    bundle = _bundle(
        reference_df=_reference_series(
            "VIX",
            ["2021-01-04", "2021-01-05", "2021-01-06"],
            values=[26.0, 24.0, 30.0],
            closes=[10.0, 99.0, 10.0],
        )
    )
    rule = AtomicRule.model_validate(
        {"kind": "atomic", "type": "series_below", "symbol": "VIX", "threshold": 25}
    )

    assert evaluate_rule(rule, bundle, 1, "QQQ") is True
    assert evaluate_rule(rule, bundle, 2, "QQQ") is False


def test_vix_series_below_falls_back_to_close() -> None:
    bundle = _bundle(
        reference_df=_reference_series(
            "VIX",
            ["2021-01-04", "2021-01-05", "2021-01-06"],
            closes=[26.0, 24.0, 30.0],
        )
    )
    rule = AtomicRule.model_validate(
        {"kind": "atomic", "type": "series_below", "symbol": "VIX", "threshold": 25}
    )

    assert evaluate_rule(rule, bundle, 1, "QQQ") is True
    assert evaluate_rule(rule, bundle, 2, "QQQ") is False


def test_dgs10_series_above_and_below_use_value() -> None:
    bundle = _bundle(
        reference_symbol="DGS10",
        reference_df=_reference_series(
            "DGS10",
            ["2021-01-04", "2021-01-05", "2021-01-06"],
            values=[4.3, 4.6, 4.4],
        ),
    )
    above = AtomicRule.model_validate(
        {"kind": "atomic", "type": "series_above", "symbol": "DGS10", "threshold": 4.5}
    )
    below = AtomicRule.model_validate(
        {"kind": "atomic", "type": "series_below", "symbol": "DGS10", "threshold": 4.5}
    )

    assert evaluate_rule(above, bundle, 1, "QQQ") is True
    assert evaluate_rule(above, bundle, 2, "QQQ") is False
    assert evaluate_rule(below, bundle, 0, "QQQ") is True
    assert evaluate_rule(below, bundle, 1, "QQQ") is False


def test_missing_reference_date_returns_false_without_forward_fill() -> None:
    bundle = _bundle(
        reference_df=_reference_series(
            "VIX",
            ["2021-01-04", "2021-01-06"],
            values=[20.0, 30.0],
        )
    )
    rule = AtomicRule.model_validate(
        {"kind": "atomic", "type": "series_below", "symbol": "VIX", "threshold": 25}
    )

    assert evaluate_rule(rule, bundle, 0, "QQQ") is True
    assert evaluate_rule(rule, bundle, 1, "QQQ") is False
    assert evaluate_rule(rule, bundle, 2, "QQQ") is False


def test_missing_reference_symbol_raises_clear_market_data_error() -> None:
    bundle = MarketDataBundle(tradable=_tradable(), references={})
    rule = AtomicRule.model_validate(
        {"kind": "atomic", "type": "series_below", "symbol": "VIX", "threshold": 25}
    )

    with pytest.raises(ValueError, match="Missing market data for reference symbol VIX"):
        evaluate_rule(rule, bundle, 0, "QQQ")


def test_runner_combines_tradable_rsi_with_reference_series_rule() -> None:
    bundle = _bundle(
        reference_df=_reference_series(
            "VIX",
            ["2021-01-04", "2021-01-05", "2021-01-06"],
            values=[30.0, 20.0, 20.0],
        )
    )
    strategy = StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 50,
                    },
                    {
                        "kind": "atomic",
                        "type": "series_below",
                        "symbol": "VIX",
                        "threshold": 25,
                    },
                ],
            }
        )
    )

    result = runner.run_simulation(bundle, strategy)

    assert result.trade_log[0]["action"] == "BUY"
    assert result.trade_log[0]["date"] == str(date(2021, 1, 5))


def test_runner_reference_series_entry_uses_exact_same_date_without_lookahead() -> None:
    bundle = _bundle(
        reference_df=_reference_series(
            "VIX",
            ["2021-01-04", "2021-01-05", "2021-01-06"],
            values=[30.0, 30.0, 20.0],
        )
    )
    strategy = StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 50,
                    },
                    {
                        "kind": "atomic",
                        "type": "series_below",
                        "symbol": "VIX",
                        "threshold": 25,
                    },
                ],
            }
        )
    )

    result = runner.run_simulation(bundle, strategy)

    assert [row["entry_signal"] for row in result.timeline] == [False, False, True]
    assert [(trade["action"], trade["date"]) for trade in result.trade_log] == [
        ("BUY", str(date(2021, 1, 6)))
    ]


def test_runner_missing_reference_date_is_no_signal_on_valid_tradable_entry_day() -> None:
    bundle = _bundle(
        reference_df=_reference_series(
            "VIX",
            ["2021-01-04", "2021-01-06"],
            values=[20.0, 30.0],
        )
    )
    strategy = StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 50,
                    },
                    {
                        "kind": "atomic",
                        "type": "series_below",
                        "symbol": "VIX",
                        "threshold": 25,
                    },
                ],
            }
        )
    )

    result = runner.run_simulation(bundle, strategy)

    assert [row["entry_signal"] for row in result.timeline] == [False, False, False]
    assert result.trade_log == []
    assert result.summary["ending_equity"] == pytest.approx(result.summary["initial_capital"])


def test_vix_add_reduce_reduces_on_exit_signal_without_profit_reduce() -> None:
    dates = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"]
    bundle = _bundle(
        dates=dates,
        closes=[100.0, 110.0, 120.0, 121.0],
        reference_df=_reference_series(
            "VIX",
            dates,
            values=[10.0, 10.0, 40.0, 40.0],
        ),
    )
    strategy = StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 15,
            },
            exit_rule={
                "kind": "atomic",
                "type": "series_above",
                "symbol": "VIX",
                "threshold": 35,
            },
            position_management={
                "scale_in_fraction": 0.25,
                "scale_out_fraction": 0.5,
                "profit_reduce_threshold": None,
            },
        )
    )

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert "SELL_REDUCE_PROFIT" not in actions
    assert actions == ["BUY", "BUY_ADD", "SELL_REDUCE", "SELL_REDUCE"]
    assert [
        (row["date"], row["exit_signal"], row["action_taken"])
        for row in result.timeline
        if row["action_taken"] == "reduce"
    ] == [
        ("2021-01-06", True, "reduce"),
        ("2021-01-07", True, "reduce"),
    ]
    assert result.summary["trade_event_count"] == 4
    assert result.summary["full_exit_count"] == 0
    assert result.summary["buy_event_count"] == 1
    assert result.summary["add_event_count"] == 1
    assert result.summary["reduce_event_count"] == 2


def test_vix_add_reduce_uses_exact_reference_dates_without_forward_fill_or_lookahead() -> None:
    dates = [
        "2021-01-04",
        "2021-01-05",
        "2021-01-06",
        "2021-01-07",
        "2021-01-08",
    ]
    bundle = _bundle(
        dates=dates,
        closes=[100.0, 100.0, 100.0, 100.0, 100.0],
        reference_df=_reference_series(
            "VIX",
            ["2021-01-04", "2021-01-06", "2021-01-08"],
            values=[10.0, 10.0, 40.0],
        ),
    )
    strategy = StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 15,
            },
            exit_rule={
                "kind": "atomic",
                "type": "series_above",
                "symbol": "VIX",
                "threshold": 35,
            },
            position_management={
                "scale_in_fraction": 0.25,
                "scale_out_fraction": 0.5,
                "profit_reduce_threshold": None,
            },
        )
    )

    result = runner.run_simulation(bundle, strategy)

    assert [(trade["date"], trade["action"]) for trade in result.trade_log] == [
        ("2021-01-04", "BUY"),
        ("2021-01-06", "BUY_ADD"),
        ("2021-01-08", "SELL_REDUCE"),
    ]
    assert [
        (row["date"], row["entry_signal"], row["exit_signal"], row["action_taken"])
        for row in result.timeline
    ] == [
        ("2021-01-04", True, False, "scale_in"),
        ("2021-01-05", False, False, ""),
        ("2021-01-06", True, False, "scale_in"),
        ("2021-01-07", False, False, ""),
        ("2021-01-08", False, True, "reduce"),
    ]
    assert "SELL_REDUCE_PROFIT" not in [
        trade["action"] for trade in result.trade_log
    ]


def test_vix_add_reduce_only_profit_reduces_when_explicitly_configured() -> None:
    dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
    bundle = _bundle(
        dates=dates,
        closes=[100.0, 110.0, 120.0],
        reference_df=_reference_series(
            "VIX",
            dates,
            values=[10.0, 10.0, 40.0],
        ),
    )
    strategy = StrategyV2.model_validate(
        _strategy_config(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 15,
            },
            exit_rule={
                "kind": "atomic",
                "type": "series_above",
                "symbol": "VIX",
                "threshold": 35,
            },
            position_management={
                "scale_in_fraction": 0.25,
                "scale_out_fraction": 0.5,
                "profit_reduce_threshold": 0.05,
            },
        )
    )

    result = runner.run_simulation(bundle, strategy)
    actions = [trade["action"] for trade in result.trade_log]

    assert "SELL_REDUCE_PROFIT" in actions
    assert actions[:2] == ["BUY", "SELL_REDUCE_PROFIT"]
