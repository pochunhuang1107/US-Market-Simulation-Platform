from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from market_simulator.platform.services.parameter_sweep import (
    ParameterSweepError,
    ParameterSweepService,
    build_sweep_request,
    generate_variant_configs,
)


def _base_rsi_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-rsi",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "QQQ",
        "reference_symbols": [],
        "start_date": "2021-01-01",
        "end_date": "2021-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 0,
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
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
    }


def test_parameter_grid_expands_to_cartesian_product() -> None:
    request = build_sweep_request(
        {
            "base_config": _base_rsi_config(),
            "grid": {
                "entry_rule.threshold": [20, 25],
                "exit_rule.threshold": [60, 65],
            },
        }
    )

    assert request["variant_count"] == 4
    assert [
        variant["parameters"]
        for variant in request["variants"]
    ] == [
        {"entry_rule.threshold": 20, "exit_rule.threshold": 60},
        {"entry_rule.threshold": 20, "exit_rule.threshold": 65},
        {"entry_rule.threshold": 25, "exit_rule.threshold": 60},
        {"entry_rule.threshold": 25, "exit_rule.threshold": 65},
    ]


def test_variant_generation_does_not_mutate_base_config() -> None:
    base_config = _base_rsi_config()
    original = json.loads(json.dumps(base_config))

    variants = generate_variant_configs(
        base_config,
        {"entry_rule.threshold": [20, 25]},
    )

    assert base_config == original
    assert variants[0]["config"]["entry_rule"]["threshold"] == 20
    assert variants[1]["config"]["entry_rule"]["threshold"] == 25
    assert variants[0]["variant_name"].startswith("qqq-rsi-sweep-001-threshold-20")


def test_variant_generation_updates_nested_composite_rule_paths_without_mutation() -> None:
    base_config = _base_rsi_config()
    base_config["entry_rule"] = {
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
    original = json.loads(json.dumps(base_config))

    variants = generate_variant_configs(
        base_config,
        {
            "entry_rule.rules[0].threshold": [25, 35],
            "entry_rule.rules[1].slow_window": [150],
        },
    )

    assert base_config == original
    assert variants[0]["parameters"] == {
        "entry_rule.rules[0].threshold": 25,
        "entry_rule.rules[1].slow_window": 150,
    }
    assert variants[0]["config"]["entry_rule"]["rules"][0]["threshold"] == 25
    assert variants[0]["config"]["entry_rule"]["rules"][1]["slow_window"] == 150
    assert variants[1]["config"]["entry_rule"]["rules"][0]["threshold"] == 35
    assert original["entry_rule"]["rules"][0]["threshold"] == 30
    assert original["entry_rule"]["rules"][1]["slow_window"] == 200


def test_max_variant_limit_returns_clear_error() -> None:
    with pytest.raises(
        ParameterSweepError,
        match="Parameter sweep is limited to 3 variants for your plan.",
    ):
        build_sweep_request(
            {
                "base_config": _base_rsi_config(),
                "grid": {
                    "entry_rule.threshold": [20, 25],
                    "exit_rule.threshold": [60, 65],
                },
                "max_variants": 3,
            }
        )


@dataclass
class FakeSimulationResult:
    summary: dict
    artifact_dir: str


class FakeSimulationService:
    def run_from_config(self, config: dict, output_dir):
        entry_threshold = config["entry_rule"]["threshold"]
        exit_threshold = config["exit_rule"]["threshold"]
        sharpe = (entry_threshold / 10) + (exit_threshold / 100)
        return FakeSimulationResult(
            summary={
                "total_return_pct": entry_threshold + exit_threshold,
                "benchmark_return_pct": 10.0,
                "alpha_vs_benchmark_pct": entry_threshold + exit_threshold - 10.0,
                "cagr_pct": entry_threshold / 2,
                "sharpe_ratio": sharpe,
                "max_drawdown_pct": -float(exit_threshold),
                "trade_count": int(entry_threshold),
            },
            artifact_dir=str(output_dir),
        )


def test_successful_small_rsi_sweep_writes_ranked_summary(tmp_path) -> None:
    service = ParameterSweepService(simulation_service=FakeSimulationService())

    result = service.run_sweep(
        {
            "base_config": _base_rsi_config(),
            "grid": {
                "entry_rule.threshold": [20, 25],
                "exit_rule.threshold": [60, 65],
            },
            "ranking_metric": "sharpe",
        },
        output_dir=tmp_path,
    )

    summary = result["summary"]
    assert summary["variant_count"] == 4
    assert summary["succeeded_count"] == 4
    assert summary["failed_count"] == 0
    assert summary["best_variant"]["parameters"] == {
        "entry_rule.threshold": 25,
        "exit_rule.threshold": 65,
    }
    assert (tmp_path / "sweep_summary.json").exists()
    assert (tmp_path / "sweep_results.csv").exists()

    persisted = json.loads((tmp_path / "sweep_summary.json").read_text(encoding="utf-8"))
    assert persisted["results"][0]["sharpe_ratio"] >= persisted["results"][1]["sharpe_ratio"]
    assert persisted["results"][0]["config"]["entry_rule"]["threshold"] == 25
    assert persisted["best_variant"]["config"]["exit_rule"]["threshold"] == 65


def test_sweep_summary_sorted_by_ranking_metric_descending(tmp_path) -> None:
    service = ParameterSweepService(simulation_service=FakeSimulationService())

    result = service.run_sweep(
        {
            "base_config": _base_rsi_config(),
            "grid": {"entry_rule.threshold": [25, 20]},
            "ranking_metric": "total_return_pct",
        },
        output_dir=tmp_path,
    )

    totals = [row["total_return_pct"] for row in result["summary"]["results"]]
    assert totals == sorted(totals, reverse=True)
