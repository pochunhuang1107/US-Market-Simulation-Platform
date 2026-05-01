from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine import runner
from market_simulator.engine.artifacts import write_artifacts
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.run_chart_service import RunChartService
from market_simulator.platform.services.parameter_sweep import ParameterSweepService
from market_simulator.reporting.metrics import FULL_EXIT_ACTIONS
from market_simulator.strategy.enricher import enrich_market_data
from market_simulator.strategy.evaluator import evaluate_rule


def _bundle(
    dates: list[str],
    closes: list[float],
    extra_columns: dict[str, list[float | int | None]] | None = None,
) -> MarketDataBundle:
    df = _market_df("SPY", dates, closes, extra_columns)
    return MarketDataBundle(tradable=df, references={})


def _market_df(
    symbol: str,
    dates: list[str],
    closes: list[float],
    extra_columns: dict[str, list[float | int | None]] | None = None,
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
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
    for name, values in (extra_columns or {}).items():
        df[name] = values
    return df


def _bundle_with_references(
    *,
    tradable_symbol: str,
    dates: list[str],
    closes: list[float],
    references: dict[str, tuple[list[str], list[float], dict[str, list[float | int | None]] | None]],
    extra_columns: dict[str, list[float | int | None]] | None = None,
) -> MarketDataBundle:
    return MarketDataBundle(
        tradable=_market_df(tradable_symbol, dates, closes, extra_columns),
        references={
            symbol: _market_df(symbol, ref_dates, ref_closes, ref_extra)
            for symbol, (ref_dates, ref_closes, ref_extra) in references.items()
        },
    )


# Future signal expansion test-plan note: when VIX/regime filters, daily candle
# pattern signals, realized-volatility filters, or ETF rotation are added, cover
# them here with synthetic bars first so Strategy V2 trust stays ahead of UI work.


def _strategy_config(
    *,
    name: str = "synthetic-correctness",
    tradable_symbol: str = "SPY",
    benchmark_symbol: str = "SPY",
    reference_symbols: list[str] | None = None,
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
        "tradable_symbol": tradable_symbol,
        "benchmark_symbol": benchmark_symbol,
        "reference_symbols": reference_symbols or [],
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


def _business_dates(count: int) -> list[str]:
    return [str(date.date()) for date in pd.date_range("2021-01-04", periods=count, freq="B")]


def _closes_from_returns(returns: list[float], *, start: float = 100.0) -> list[float]:
    closes = [start]
    for daily_return in returns:
        closes.append(closes[-1] * (1.0 + daily_return))
    return closes


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

    def fake_evaluate_rule(rule, _bundle, index, _tradable_symbol=None):
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


def test_core_overlay_exit_liquidates_only_overlay_and_reconciles_sleeves() -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-02-01", "2021-03-01"],
            [100.0, 80.0, 120.0],
        ),
        _strategy(
            name="core-overlay-exit-reconciliation",
            exit_rule={
                "kind": "atomic",
                "type": "month_in",
                "symbol": "SPY",
                "month_values": [2],
            },
            core_overlay={
                "enabled": True,
                "core_allocation_pct": 0.60,
            },
        ),
    )

    assert [(trade["action"], trade["sleeve"]) for trade in result.trade_log] == [
        ("BUY", "overlay"),
        ("SELL_ALL", "overlay"),
    ]
    assert [row["core_shares"] for row in result.timeline] == [6, 6, 6]
    assert result.timeline[1]["overlay_position_shares"] == 0
    assert result.timeline[-1]["core_equity"] == pytest.approx(720.0)
    assert result.timeline[-1]["overlay_equity"] == pytest.approx(320.0)
    assert result.timeline[-1]["strategy_equity"] == pytest.approx(1040.0)
    assert result.summary["ending_equity"] == pytest.approx(1040.0)
    assert (
        result.sleeve_summary["core_pnl"] + result.sleeve_summary["overlay_pnl"]
        == pytest.approx(result.summary["ending_equity"] - result.summary["initial_capital"])
    )
    for row in result.timeline:
        assert row["strategy_equity"] == pytest.approx(
            row["core_equity"] + row["overlay_equity"]
        )


def test_partial_take_profit_sells_fraction_without_closing_position() -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-01-05", "2021-01-06"],
            [100.0, 110.0, 120.0],
            extra_columns={
                "sma_1": [100.0, 90.0, 90.0],
                "sma_3": [90.0, 120.0, 120.0],
            },
        ),
        _strategy(
            name="partial-take-profit",
            entry_rule={
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "SPY",
                "fast_window": 1,
                "slow_window": 3,
            },
            risk={
                "partial_take_profit": {
                    "trigger_profit_pct": 0.05,
                    "sell_fraction_of_position": 0.5,
                    "max_triggers": 1,
                }
            },
        ),
    )

    assert [trade["action"] for trade in result.trade_log] == [
        "BUY",
        "SELL_PARTIAL_TAKE_PROFIT",
    ]
    assert result.trade_log[1]["shares"] == 5
    assert result.trade_log[1]["net_pnl"] == pytest.approx(50.0)
    assert result.timeline[1]["overlay_position_shares"] == 5
    assert result.timeline[-1]["overlay_position_shares"] == 5
    assert result.summary["trade_count"] == 0
    assert result.summary["ending_equity"] == pytest.approx(1150.0)


def test_allocation_entry_value_scales_in_until_max_position_cap() -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"],
            [100.0, 100.0, 100.0, 100.0],
        ),
        _strategy(
            name="allocation-entry-value-and-max-position",
            allocation={
                "entry_mode": "percent_of_equity",
                "entry_value": 0.25,
                "max_position_pct": 0.5,
            },
        ),
    )

    assert [(trade["action"], trade["shares"]) for trade in result.trade_log] == [
        ("BUY", 2),
        ("BUY_ADD", 2),
        ("BUY_ADD", 1),
    ]
    assert max(row["overlay_position_shares"] for row in result.timeline) == 5
    assert result.timeline[-1]["overlay_position_market_value"] == pytest.approx(500.0)


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


def test_artifact_payloads_reconcile_yearly_report_benchmark_and_chart_data(
    tmp_path: Path,
) -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-01-05", "2022-01-04"],
            [100.0, 110.0, 121.0],
        ),
        _strategy(name="artifact-chart-data-consistency"),
    )

    artifact_dir = write_artifacts(result, tmp_path)
    summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
    timeline = pd.read_csv(artifact_dir / "timeline.csv")
    yearly = pd.read_csv(artifact_dir / "yearly_report.csv")

    expected_total_return = (
        timeline.iloc[-1]["strategy_equity"] / timeline.iloc[0]["strategy_equity"] - 1.0
    ) * 100.0
    assert summary["total_return_pct"] == pytest.approx(expected_total_return)
    assert "benchmark_equity" in timeline.columns
    assert timeline["benchmark_equity"].notna().all()
    assert yearly.iloc[0]["end_equity"] == pytest.approx(timeline.iloc[1]["strategy_equity"])
    assert yearly.iloc[-1]["end_equity"] == pytest.approx(summary["ending_equity"])

    chart_service = object.__new__(RunChartService)
    chart_data = chart_service.load_chart_data(
        {
            "timeline": str(artifact_dir / "timeline.csv"),
            "monthly_returns": str(artifact_dir / "monthly_returns.csv"),
            "trade_log": str(artifact_dir / "trade_log.csv"),
        }
    )
    assert chart_data["equity_curve"][-1]["strategy_equity"] == pytest.approx(
        summary["ending_equity"]
    )
    assert chart_data["drawdown_curve"]
    assert chart_data["trade_markers"][0]["side"] == "BUY"


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

    persisted_summary = json.loads((tmp_path / "sweep_summary.json").read_text(encoding="utf-8"))
    persisted_rows = pd.read_csv(tmp_path / "sweep_results.csv")
    assert persisted_summary["variant_count"] == 4
    assert len(persisted_rows) == persisted_summary["variant_count"]
    assert persisted_summary["best_variant"]["variant_id"] == rows[0]["variant_id"]
    assert Path(persisted_summary["best_variant"]["artifact_dir"], "timeline.csv").exists()


def test_relative_return_above_compares_primary_excess_return_to_threshold() -> None:
    dates = _business_dates(21)
    bundle = _bundle_with_references(
        tradable_symbol="QQQ",
        dates=dates,
        closes=[100.0] * 20 + [108.0],
        references={
            "SPY": (["2020-12-31", *dates], [999.0] + [100.0] * 20 + [104.0], None),
        },
    )
    strategy = _strategy(
        name="qqq-beats-spy",
        tradable_symbol="QQQ",
        benchmark_symbol="SPY",
        reference_symbols=["SPY"],
        entry_rule={
            "kind": "atomic",
            "type": "relative_return_above",
            "symbol": "QQQ",
            "reference_symbol": "SPY",
            "lookback": 20,
            "threshold": 0.03,
        },
    )

    enriched = enrich_market_data(bundle, strategy)

    assert evaluate_rule(strategy.entry_rule, enriched, 20, strategy.tradable_symbol) is True


def test_relative_return_above_returns_false_when_excess_return_is_below_threshold() -> None:
    dates = _business_dates(21)
    bundle = _bundle_with_references(
        tradable_symbol="QQQ",
        dates=dates,
        closes=[100.0] * 20 + [106.0],
        references={
            "SPY": (dates, [100.0] * 20 + [104.0], None),
        },
    )
    strategy = _strategy(
        name="qqq-does-not-beat-spy-enough",
        tradable_symbol="QQQ",
        benchmark_symbol="SPY",
        reference_symbols=["SPY"],
        entry_rule={
            "kind": "atomic",
            "type": "relative_return_above",
            "symbol": "QQQ",
            "reference_symbol": "SPY",
            "lookback": 20,
            "threshold": 0.03,
        },
    )

    enriched = enrich_market_data(bundle, strategy)

    assert evaluate_rule(strategy.entry_rule, enriched, 20, strategy.tradable_symbol) is False


def test_relative_return_above_handles_missing_lookback_and_reference_date_safely() -> None:
    dates = _business_dates(21)
    bundle = _bundle_with_references(
        tradable_symbol="QQQ",
        dates=dates,
        closes=[100.0] * 20 + [108.0],
        references={
            "SPY": (dates[:-1], [100.0] * 20, None),
        },
    )
    strategy = _strategy(
        name="qqq-missing-spy-date",
        tradable_symbol="QQQ",
        benchmark_symbol="SPY",
        reference_symbols=["SPY"],
        entry_rule={
            "kind": "atomic",
            "type": "relative_return_above",
            "symbol": "QQQ",
            "reference_symbol": "SPY",
            "lookback": 20,
            "threshold": 0.03,
        },
    )

    enriched = enrich_market_data(bundle, strategy)

    assert evaluate_rule(strategy.entry_rule, enriched, 0, strategy.tradable_symbol) is False
    assert evaluate_rule(strategy.entry_rule, enriched, 20, strategy.tradable_symbol) is False


def test_realized_volatility_column_uses_close_to_close_returns_and_annualization() -> None:
    returns = [0.01, -0.01, 0.02, -0.02, 0.015]
    closes = _closes_from_returns(returns)
    dates = _business_dates(len(closes))
    bundle = _bundle(dates, closes)
    strategy = _strategy(
        name="spy-realized-volatility",
        entry_rule={
            "kind": "atomic",
            "type": "realized_volatility_below",
            "symbol": "SPY",
            "lookback": 5,
            "threshold": 1.0,
        },
    )

    enriched = enrich_market_data(bundle, strategy)
    expected = pd.Series(returns).std() * math.sqrt(252)

    assert math.isnan(enriched.tradable.loc[4, "realized_volatility_5"])
    assert enriched.tradable.loc[5, "realized_volatility_5"] == pytest.approx(expected)


def test_realized_volatility_below_and_above_evaluate_thresholds_and_nan_safely() -> None:
    low_vol_closes = _closes_from_returns([0.001, -0.001] * 10)
    high_vol_closes = _closes_from_returns([0.02, -0.02] * 10)
    dates = _business_dates(len(low_vol_closes))

    below_strategy = _strategy(
        name="spy-low-vol",
        entry_rule={
            "kind": "atomic",
            "type": "realized_volatility_below",
            "symbol": "SPY",
            "lookback": 20,
            "threshold": 0.25,
        },
    )
    below_enriched = enrich_market_data(_bundle(dates, low_vol_closes), below_strategy)

    assert evaluate_rule(below_strategy.entry_rule, below_enriched, 19, below_strategy.tradable_symbol) is False
    assert evaluate_rule(below_strategy.entry_rule, below_enriched, 20, below_strategy.tradable_symbol) is True

    below_false_enriched = enrich_market_data(_bundle(dates, high_vol_closes), below_strategy)
    assert evaluate_rule(below_strategy.entry_rule, below_false_enriched, 20, below_strategy.tradable_symbol) is False

    above_strategy = _strategy(
        name="spy-high-vol",
        entry_rule={
            "kind": "atomic",
            "type": "realized_volatility_above",
            "symbol": "SPY",
            "lookback": 20,
            "threshold": 0.25,
        },
    )
    above_enriched = enrich_market_data(_bundle(dates, high_vol_closes), above_strategy)
    above_false_enriched = enrich_market_data(_bundle(dates, low_vol_closes), above_strategy)

    assert evaluate_rule(above_strategy.entry_rule, above_enriched, 20, above_strategy.tradable_symbol) is True
    assert evaluate_rule(above_strategy.entry_rule, above_false_enriched, 20, above_strategy.tradable_symbol) is False


def test_reference_symbol_realized_volatility_rule_uses_reference_dataframe() -> None:
    dates = _business_dates(21)
    bundle = _bundle_with_references(
        tradable_symbol="QQQ",
        dates=dates,
        closes=_closes_from_returns([0.001, -0.001] * 10),
        references={
            "SPY": (dates, _closes_from_returns([0.02, -0.02] * 10), None),
        },
    )
    strategy = _strategy(
        name="qqq-spy-vol-filter",
        tradable_symbol="QQQ",
        benchmark_symbol="SPY",
        reference_symbols=["SPY"],
        entry_rule={
            "kind": "atomic",
            "type": "realized_volatility_above",
            "symbol": "SPY",
            "lookback": 20,
            "threshold": 0.25,
        },
    )

    enriched = enrich_market_data(bundle, strategy)

    assert "realized_volatility_20" not in enriched.tradable.columns
    assert evaluate_rule(strategy.entry_rule, enriched, 20, strategy.tradable_symbol) is True


def test_composite_rsi_and_realized_volatility_rule_evaluates_children() -> None:
    dates = _business_dates(1)
    bundle = _bundle(
        dates,
        [100.0],
        extra_columns={"rsi_14": [25.0], "realized_volatility_20": [0.20]},
    )
    strategy = _strategy(
        name="rsi-and-low-vol",
        entry_rule={
            "kind": "group",
            "operator": "AND",
            "rules": [
                {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "SPY",
                    "lookback": 14,
                    "threshold": 30,
                },
                {
                    "kind": "atomic",
                    "type": "realized_volatility_below",
                    "symbol": "SPY",
                    "lookback": 20,
                    "threshold": 0.25,
                },
            ],
        },
    )

    assert evaluate_rule(strategy.entry_rule, bundle, 0, strategy.tradable_symbol) is True


def test_composite_rsi_or_realized_volatility_exit_rule_evaluates_children() -> None:
    dates = _business_dates(1)
    bundle = _bundle(
        dates,
        [100.0],
        extra_columns={"rsi_14": [50.0], "realized_volatility_20": [0.40]},
    )
    strategy = _strategy(
        name="rsi-or-high-vol-exit",
        exit_rule={
            "kind": "group",
            "operator": "OR",
            "rules": [
                {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "SPY",
                    "lookback": 14,
                    "threshold": 70,
                },
                {
                    "kind": "atomic",
                    "type": "realized_volatility_above",
                    "symbol": "SPY",
                    "lookback": 20,
                    "threshold": 0.35,
                },
            ],
        },
    )

    assert evaluate_rule(strategy.exit_rule, bundle, 0, strategy.tradable_symbol) is True


def test_realized_volatility_strategy_runs_end_to_end_on_synthetic_prices() -> None:
    closes = _closes_from_returns([0.001, -0.001] * 10 + [0.03, -0.03] * 11)
    dates = _business_dates(len(closes))
    strategy = _strategy(
        name="qqq-realized-volatility-run",
        tradable_symbol="QQQ",
        benchmark_symbol="QQQ",
        initial_capital=100000.0,
        entry_rule={
            "kind": "atomic",
            "type": "realized_volatility_below",
            "symbol": "QQQ",
            "lookback": 20,
            "threshold": 0.25,
        },
        exit_rule={
            "kind": "atomic",
            "type": "realized_volatility_above",
            "symbol": "QQQ",
            "lookback": 20,
            "threshold": 0.35,
        },
    )

    result = _run(
        MarketDataBundle(
            tradable=_market_df("QQQ", dates, closes),
            references={},
        ),
        strategy,
    )

    assert len(result.timeline) == len(dates)
    assert any(trade["action"] == "BUY" for trade in result.trade_log)
    assert any(trade["action"] in FULL_EXIT_ACTIONS for trade in result.trade_log)


def test_reference_symbol_sma_rule_evaluates_reference_dataframe() -> None:
    bundle = _bundle_with_references(
        tradable_symbol="QQQ",
        dates=["2021-01-04"],
        closes=[90.0],
        extra_columns={"sma_1": [90.0], "sma_200": [100.0]},
        references={
            "SPY": (
                ["2021-01-04"],
                [110.0],
                {"sma_1": [110.0], "sma_200": [100.0]},
            ),
        },
    )
    strategy = _strategy(
        name="qqq-spy-sma-filter",
        tradable_symbol="QQQ",
        benchmark_symbol="SPY",
        reference_symbols=["SPY"],
        entry_rule={
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 200,
        },
    )

    enriched = enrich_market_data(bundle, strategy)

    assert evaluate_rule(strategy.entry_rule, enriched, 0, strategy.tradable_symbol) is True


def test_composite_rule_evaluates_tradable_and_reference_children_against_correct_symbols() -> None:
    bundle = _bundle_with_references(
        tradable_symbol="QQQ",
        dates=["2021-01-04"],
        closes=[90.0],
        extra_columns={"rsi_2": [25.0], "sma_1": [90.0], "sma_200": [100.0]},
        references={
            "SPY": (
                ["2021-01-04"],
                [110.0],
                {"sma_1": [110.0], "sma_200": [100.0]},
            ),
        },
    )
    strategy = _strategy(
        name="qqq-rsi-and-spy-sma",
        tradable_symbol="QQQ",
        benchmark_symbol="SPY",
        reference_symbols=["SPY"],
        entry_rule={
            "kind": "group",
            "operator": "AND",
            "rules": [
                {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "QQQ",
                    "lookback": 2,
                    "threshold": 30.0,
                },
                {
                    "kind": "atomic",
                    "type": "sma_above",
                    "symbol": "SPY",
                    "fast_window": 1,
                    "slow_window": 200,
                },
            ],
        },
    )

    enriched = enrich_market_data(bundle, strategy)

    assert evaluate_rule(strategy.entry_rule, enriched, 0, strategy.tradable_symbol) is True


def test_missing_reference_symbol_data_raises_clear_error() -> None:
    dates = _business_dates(21)
    bundle = _bundle_with_references(
        tradable_symbol="QQQ",
        dates=dates,
        closes=[100.0] * 20 + [108.0],
        references={},
    )
    strategy = _strategy(
        name="missing-spy",
        tradable_symbol="QQQ",
        benchmark_symbol="SPY",
        reference_symbols=["SPY"],
        entry_rule={
            "kind": "atomic",
            "type": "relative_return_above",
            "symbol": "QQQ",
            "reference_symbol": "SPY",
            "lookback": 20,
            "threshold": 0.03,
        },
    )

    with pytest.raises(ValueError, match="Missing market data for reference symbol SPY"):
        enrich_market_data(bundle, strategy)


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
                        "threshold": -0.01,
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


def test_composite_entry_and_exit_groups_support_or_and_nested_not_truth_tables() -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"],
            [100.0, 100.0, 100.0, 100.0],
            extra_columns={
                "rsi_2": [50.0, 25.0, 80.0, 80.0],
                "sma_1": [90.0, 90.0, 120.0, 90.0],
                "sma_3": [100.0, 100.0, 100.0, 100.0],
            },
        ),
        _strategy(
            name="composite-or-entry-and-exit",
            entry_rule={
                "kind": "group",
                "operator": "OR",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "SPY",
                        "lookback": 2,
                        "threshold": 30.0,
                    },
                    {
                        "kind": "atomic",
                        "type": "sma_above",
                        "symbol": "SPY",
                        "fast_window": 1,
                        "slow_window": 3,
                    },
                ],
            },
            exit_rule={
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "SPY",
                        "lookback": 2,
                        "threshold": 70.0,
                    },
                    {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "sma_above",
                            "symbol": "SPY",
                            "fast_window": 1,
                            "slow_window": 3,
                        },
                    },
                ],
            },
        ),
    )

    assert [(trade["action"], trade["date"]) for trade in result.trade_log] == [
        ("BUY", "2021-01-05"),
        ("SELL_ALL", "2021-01-07"),
    ]
    assert [row["entry_signal"] for row in result.timeline] == [False, True, True, False]
    assert [row["exit_signal"] for row in result.timeline] == [False, False, False, True]


def test_mixed_composite_rules_with_nested_not_do_not_trigger_early() -> None:
    result = _run(
        _bundle(
            ["2021-01-04", "2021-01-05", "2021-01-06", "2021-02-01"],
            [100.0, 100.0, 100.0, 100.0],
            extra_columns={
                "rsi_2": [80.0, 40.0, 40.0, 60.0],
                "sma_1": [120.0, 90.0, 120.0, 90.0],
                "sma_3": [100.0, 100.0, 100.0, 100.0],
            },
        ),
        _strategy(
            name="nested-not-composite",
            entry_rule={
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "not",
                        "rule": {
                            "kind": "group",
                            "operator": "OR",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_above",
                                    "symbol": "SPY",
                                    "lookback": 2,
                                    "threshold": 70.0,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "month_in",
                                    "symbol": "SPY",
                                    "month_values": [2],
                                },
                            ],
                        },
                    },
                    {
                        "kind": "atomic",
                        "type": "sma_above",
                        "symbol": "SPY",
                        "fast_window": 1,
                        "slow_window": 3,
                    },
                ],
            },
            exit_rule={
                "kind": "group",
                "operator": "OR",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "SPY",
                        "lookback": 2,
                        "threshold": 70.0,
                    },
                    {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "month_in",
                                "symbol": "SPY",
                                "month_values": [2],
                            },
                            {
                                "kind": "not",
                                "rule": {
                                    "kind": "atomic",
                                    "type": "sma_above",
                                    "symbol": "SPY",
                                    "fast_window": 1,
                                    "slow_window": 3,
                                },
                            },
                        ],
                    },
                ],
            },
        ),
    )

    assert [(trade["action"], trade["date"]) for trade in result.trade_log] == [
        ("BUY", "2021-01-06"),
        ("SELL_ALL", "2021-02-01"),
    ]
    assert [row["entry_signal"] for row in result.timeline] == [False, False, True, False]
    assert [row["exit_signal"] for row in result.timeline] == [True, False, False, True]


def test_composite_rule_evaluation_is_order_independent_for_and_or_groups() -> None:
    bundle = _bundle(
        ["2021-01-04", "2021-01-05", "2021-01-06"],
        [100.0, 100.0, 100.0],
        extra_columns={
            "rsi_2": [20.0, 80.0, 20.0],
            "sma_1": [120.0, 120.0, 90.0],
            "sma_3": [100.0, 100.0, 100.0],
        },
    )
    rsi_below = {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "SPY",
        "lookback": 2,
        "threshold": 30.0,
    }
    price_above_sma = {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 3,
    }

    def signals(entry_rule: dict) -> list[bool]:
        strategy = _strategy(name="order-independent", entry_rule=entry_rule)
        enriched = enrich_market_data(bundle, strategy)
        return [
            evaluate_rule(strategy.entry_rule, enriched, index)
            for index in range(len(enriched.tradable))
        ]

    assert signals({"kind": "group", "operator": "AND", "rules": [rsi_below, price_above_sma]}) == [
        True,
        False,
        False,
    ]
    assert signals({"kind": "group", "operator": "AND", "rules": [price_above_sma, rsi_below]}) == [
        True,
        False,
        False,
    ]
    assert signals({"kind": "group", "operator": "OR", "rules": [rsi_below, price_above_sma]}) == [
        True,
        True,
        True,
    ]
    assert signals({"kind": "group", "operator": "OR", "rules": [price_above_sma, rsi_below]}) == [
        True,
        True,
        True,
    ]


def test_price_vs_sma_rule_and_sma_crossover_rule_remain_distinct() -> None:
    bundle = _bundle(
        ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"],
        [100.0, 101.0, 99.0, 99.0],
        extra_columns={
            "sma_1": [101.0, 101.0, 99.0, 99.0],
            "sma_200": [100.0, 100.0, 100.0, 100.0],
            "sma_20": [90.0, 90.0, 90.0, 110.0],
            "sma_50": [100.0, 100.0, 100.0, 100.0],
        },
    )
    strategy = _strategy(
        name="sma-distinction",
        entry_rule={
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 200,
        },
        exit_rule={
            "kind": "atomic",
            "type": "sma_cross_above",
            "symbol": "SPY",
            "fast_window": 20,
            "slow_window": 50,
        },
    )

    enriched = enrich_market_data(bundle, strategy)

    price_above_sma_signals = [
        evaluate_rule(strategy.entry_rule, enriched, index)
        for index in range(len(enriched.tradable))
    ]
    crossover_signals = [
        evaluate_rule(strategy.exit_rule, enriched, index)
        for index in range(len(enriched.tradable))
    ]
    assert price_above_sma_signals == [True, True, False, False]
    assert crossover_signals == [False, False, False, True]

    result = _run(bundle, strategy)
    assert [(trade["action"], trade["date"]) for trade in result.trade_log] == [
        ("BUY", "2021-01-04"),
        ("SELL_ALL", "2021-01-07"),
    ]
