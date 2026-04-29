from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine import runner
from market_simulator.engine.artifacts import write_artifacts
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.parameter_sweep import ParameterSweepService
from market_simulator.reporting.metrics import FULL_EXIT_ACTIONS


def _bundle(dates: list[str], closes: list[float]) -> MarketDataBundle:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "symbol": "SPY",
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
            "vwap": closes,
            "transactions": [1_000.0] * len(closes),
        }
    )
    return MarketDataBundle(tradable=df, references={})


def _strategy_config(
    *,
    name: str = "synthetic-correctness",
    initial_capital: float = 1000.0,
    transaction_cost_bps: float = 0.0,
    entry_rule: dict | None = None,
    exit_rule: dict | None = None,
    risk: dict | None = None,
    allocation: dict | None = None,
    core_overlay: dict | None = None,
) -> dict:
    return {
        "schema_version": "2.0",
        "name": name,
        "tradable_symbol": "SPY",
        "benchmark_symbol": "SPY",
        "reference_symbols": [],
        "start_date": "2021-01-01",
        "end_date": "2021-12-31",
        "initial_capital": initial_capital,
        "transaction_cost_bps": transaction_cost_bps,
        "allocation": allocation
        or {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": entry_rule
        or {
            "kind": "atomic",
            "type": "month_in",
            "symbol": "SPY",
            "month_values": [1],
        },
        "exit_rule": exit_rule
        or {
            "kind": "atomic",
            "type": "month_in",
            "symbol": "SPY",
            "month_values": [12],
        },
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
            **(risk or {}),
        },
        "core_overlay": core_overlay
        or {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
    }


def _strategy(**kwargs) -> StrategyV2:
    return StrategyV2.model_validate(_strategy_config(**kwargs))


def _run(bundle: MarketDataBundle, strategy: StrategyV2):
    return runner.run_simulation(bundle, strategy)


def _full_exits(trades: list[dict]) -> list[dict]:
    return [trade for trade in trades if trade["action"] in FULL_EXIT_ACTIONS]


def test_buy_and_hold_baseline_returns_ten_percent_before_costs() -> None:
    result = _run(
        _bundle(["2021-01-04", "2021-01-05"], [100.0, 110.0]),
        _strategy(name="buy-and-hold-100-to-110"),
    )

    assert result.trade_log == [
        {
            "date": "2021-01-04",
            "action": "BUY",
            "shares": 10,
            "price": 100.0,
            "fee": 0.0,
            "sleeve": "overlay",
        }
    ]
    assert result.summary["ending_equity"] == pytest.approx(1100.0)
    assert result.summary["total_return_pct"] == pytest.approx(10.0)
    assert result.summary["benchmark_return_pct"] == pytest.approx(10.0)
    assert result.timeline[-1]["strategy_equity"] == pytest.approx(1100.0)
    assert result.timeline[-1]["benchmark_equity"] == pytest.approx(1100.0)


def test_simple_entry_exit_trade_records_dates_count_equity_and_realized_return() -> None:
    result = _run(
        _bundle(["2021-01-04", "2021-01-05", "2021-02-01"], [100.0, 110.0, 120.0]),
        _strategy(
            name="simple-entry-exit",
            exit_rule={
                "kind": "atomic",
                "type": "month_in",
                "symbol": "SPY",
                "month_values": [2],
            },
        ),
    )

    assert [trade["action"] for trade in result.trade_log] == ["BUY", "SELL_ALL"]
    assert result.trade_log[0]["date"] == "2021-01-04"
    assert result.trade_log[1]["date"] == "2021-02-01"
    assert result.summary["trade_count"] == 1
    assert result.summary["ending_equity"] == pytest.approx(1200.0)
    assert result.summary["total_return_pct"] == pytest.approx(20.0)
    assert result.trade_log[1]["gross_pnl"] == pytest.approx(200.0)
    assert result.trade_log[1]["net_pnl"] == pytest.approx(200.0)


def test_transaction_cost_reduces_final_equity_and_is_reported_consistently() -> None:
    result = _run(
        _bundle(["2021-01-04", "2021-02-01"], [100.0, 120.0]),
        _strategy(
            name="simple-entry-exit-with-costs",
            initial_capital=1010.0,
            transaction_cost_bps=100.0,
            exit_rule={
                "kind": "atomic",
                "type": "month_in",
                "symbol": "SPY",
                "month_values": [2],
            },
        ),
    )

    buy, sell = result.trade_log
    assert buy["fee"] == pytest.approx(10.0)
    assert sell["fee"] == pytest.approx(12.0)
    assert sell["gross_pnl"] == pytest.approx(200.0)
    assert sell["net_pnl"] == pytest.approx(188.0)
    assert result.timeline[-1]["overlay_fees_paid"] == pytest.approx(22.0)
    assert result.summary["ending_equity"] == pytest.approx(1188.0)
    assert result.summary["total_return_pct"] == pytest.approx(17.6238)


def test_max_drawdown_pct_uses_peak_to_trough_equity_decline() -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"],
            [100.0, 110.0, 88.0, 99.0],
        ),
        _strategy(name="known-drawdown"),
    )

    assert [row["strategy_equity"] for row in result.timeline] == [
        1000.0,
        1100.0,
        880.0,
        990.0,
    ]
    assert result.summary["max_drawdown_pct"] == pytest.approx(-20.0)
    assert result.summary["benchmark_max_drawdown_pct"] == pytest.approx(-20.0)


def test_stop_loss_exit_occurs_when_price_drops_below_threshold() -> None:
    result = _run(
        _bundle(["2021-01-04", "2021-02-01", "2021-03-01"], [100.0, 89.0, 90.0]),
        _strategy(
            name="stop-loss",
            risk={"stop_loss_pct": 0.10},
        ),
    )

    assert [trade["action"] for trade in result.trade_log] == ["BUY", "SELL_ALL_STOP_LOSS"]
    assert result.trade_log[1]["date"] == "2021-02-01"
    assert result.trade_log[1]["net_pnl"] == pytest.approx(-110.0)
    assert result.events == [
        {
            "date": "2021-02-01",
            "event_type": "STOP_LOSS",
            "details": "Overlay sold 10 shares",
        }
    ]
    assert result.summary["ending_equity"] == pytest.approx(890.0)


def test_take_profit_exit_occurs_when_price_rises_beyond_threshold() -> None:
    result = _run(
        _bundle(["2021-01-04", "2021-02-01", "2021-03-01"], [100.0, 111.0, 112.0]),
        _strategy(
            name="take-profit",
            risk={"take_profit_pct": 0.10},
        ),
    )

    assert [trade["action"] for trade in result.trade_log] == ["BUY", "SELL_ALL_TAKE_PROFIT"]
    assert result.trade_log[1]["date"] == "2021-02-01"
    assert result.trade_log[1]["net_pnl"] == pytest.approx(110.0)
    assert result.events == [
        {
            "date": "2021-02-01",
            "event_type": "TAKE_PROFIT",
            "details": "Overlay sold 10 shares",
        }
    ]
    assert result.summary["ending_equity"] == pytest.approx(1110.0)


def test_cooldown_prevents_immediate_reentry_until_cooldown_bars_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = _strategy(name="cooldown", risk={"cooldown_bars": 2})
    bundle = _bundle(
        ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"],
        [100.0, 100.0, 100.0, 100.0, 100.0],
    )

    def fake_evaluate_rule(rule, _bundle, index):
        if getattr(rule, "type", None) == "month_in" and rule.month_values == [1]:
            return True
        if getattr(rule, "type", None) == "month_in" and rule.month_values == [12]:
            return index == 1
        return False

    monkeypatch.setattr(runner, "evaluate_rule", fake_evaluate_rule)
    result = _run(bundle, strategy)

    assert [row["action_taken"] for row in result.timeline] == [
        "scale_in",
        "exit",
        "",
        "",
        "scale_in",
    ]
    # Current timeline semantics mark the exit bar itself as cooldown-active after
    # recording the exit; the important behavior is that no same-bar re-entry occurs.
    assert [row["cooldown_active"] for row in result.timeline] == [
        False,
        True,
        True,
        True,
        False,
    ]
    assert [trade["date"] for trade in result.trade_log] == [
        "2021-01-04",
        "2021-01-05",
        "2021-01-08",
    ]


def test_core_overlay_keeps_core_invested_and_limits_overlay_to_tactical_sleeve() -> None:
    result = _run(
        _bundle(["2021-01-04", "2021-01-05"], [100.0, 110.0]),
        _strategy(
            name="core-overlay-60-40",
            core_overlay={
                "enabled": True,
                "core_allocation_pct": 0.60,
            },
        ),
    )

    first = result.timeline[0]
    final = result.timeline[-1]
    assert first["core_shares"] == 6
    assert first["overlay_position_shares"] == 4
    assert first["core_equity"] == pytest.approx(600.0)
    assert first["overlay_equity"] == pytest.approx(400.0)
    assert final["core_market_value"] == pytest.approx(660.0)
    assert final["overlay_position_market_value"] == pytest.approx(440.0)
    assert result.summary["ending_equity"] == pytest.approx(1100.0)
    assert result.sleeve_summary["core_return_pct"] == pytest.approx(10.0)
    assert result.sleeve_summary["overlay_return_pct"] == pytest.approx(10.0)


def test_written_artifacts_are_consistent_with_completed_simulation(tmp_path: Path) -> None:
    result = _run(
        _bundle(["2021-01-04", "2021-01-05", "2021-02-01"], [100.0, 110.0, 120.0]),
        _strategy(
            name="artifact-consistency",
            exit_rule={
                "kind": "atomic",
                "type": "month_in",
                "symbol": "SPY",
                "month_values": [2],
            },
        ),
    )

    artifact_dir = write_artifacts(result, tmp_path)
    summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
    timeline = pd.read_csv(artifact_dir / "timeline.csv")
    trades = pd.read_csv(artifact_dir / "trade_log.csv")

    assert summary["ending_equity"] == pytest.approx(timeline.iloc[-1]["strategy_equity"])
    assert summary["trade_count"] == int(trades["action"].isin(FULL_EXIT_ACTIONS).sum())
    expected_benchmark_return = (
        timeline.iloc[-1]["benchmark_equity"] / summary["initial_capital"] - 1.0
    ) * 100
    assert summary["benchmark_return_pct"] == pytest.approx(expected_benchmark_return)


@dataclass
class SyntheticSimulationService:
    bundle: MarketDataBundle

    def run_from_config(self, config: dict, output_dir: str | Path):
        strategy = StrategyV2.model_validate(config)
        result = runner.run_simulation(self.bundle, strategy)
        artifact_dir = write_artifacts(result, output_dir)
        result.artifact_dir = str(artifact_dir)
        return result


def test_parameter_sweep_rows_match_variant_summaries_and_rank_by_metric(tmp_path: Path) -> None:
    service = ParameterSweepService(
        simulation_service=SyntheticSimulationService(
            _bundle(["2021-01-04", "2021-01-05"], [100.0, 120.0])
        )
    )
    base_config = _strategy_config(
        name="synthetic-sweep",
        initial_capital=1005.0,
    )

    result = service.run_sweep(
        {
            "base_config": base_config,
            "grid": {
                "allocation.max_position_pct": [0.5, 1.0],
                "transaction_cost_bps": [0.0, 50.0],
            },
            "ranking_metric": "total_return_pct",
        },
        output_dir=tmp_path,
    )

    rows = result["summary"]["results"]
    assert len(rows) == 4
    assert [row["total_return_pct"] for row in rows] == sorted(
        [row["total_return_pct"] for row in rows],
        reverse=True,
    )
    assert rows[0]["parameters"] == {
        "allocation.max_position_pct": 1.0,
        "transaction_cost_bps": 0.0,
    }

    for row in rows:
        variant_summary = json.loads(
            (Path(row["artifact_dir"]) / "summary.json").read_text(encoding="utf-8")
        )
        assert row["total_return_pct"] == variant_summary["total_return_pct"]
        assert row["benchmark_return_pct"] == variant_summary["benchmark_return_pct"]
        assert row["max_drawdown_pct"] == variant_summary["max_drawdown_pct"]
        assert row["trade_count"] == variant_summary["trade_count"]


def test_composite_entry_and_exit_groups_drive_expected_trade_dates() -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-01-05", "2021-01-06", "2021-02-01"],
            [100.0, 106.0, 105.0, 107.0],
        ),
        _strategy(
            name="composite-and-or",
            initial_capital=1060.0,
            entry_rule={
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "month_in",
                        "symbol": "SPY",
                        "month_values": [1],
                    },
                    {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "SPY",
                        "reference_symbol": "SPY",
                        "lookback": 1,
                        "threshold": 0.05,
                    },
                ],
            },
            exit_rule={
                "kind": "group",
                "operator": "OR",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "month_in",
                        "symbol": "SPY",
                        "month_values": [2],
                    },
                    {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "SPY",
                        "reference_symbol": "SPY",
                        "lookback": 1,
                        "threshold": 0.50,
                    },
                ],
            },
        ),
    )

    assert [(trade["action"], trade["date"]) for trade in result.trade_log] == [
        ("BUY", "2021-01-05"),
        ("SELL_ALL", "2021-02-01"),
    ]
    assert result.timeline[0]["entry_signal"] is False
    assert result.timeline[1]["entry_signal"] is True
    assert result.timeline[-1]["exit_signal"] is True
    assert result.summary["trade_count"] == 1
    assert result.summary["ending_equity"] == pytest.approx(1070.0)
