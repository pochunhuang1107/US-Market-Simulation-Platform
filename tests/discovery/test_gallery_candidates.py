from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from market_simulator.discovery.gallery_candidates import (
    CandidateConfig,
    PeriodSpec,
    _MarketDataLoader,
    _universe_equal_weight_buy_hold_metrics,
    build_candidate_cache_key,
    build_candidate_flags,
    build_evaluation_metadata,
    build_split_periods,
    dedupe_candidate_configs,
    evaluate_candidates_with_cache,
    generate_candidate_configs,
    max_drawdown_pct_from_equity,
    rank_candidate_rows,
    run_discovery,
    score_dual_benchmark_metrics,
    select_candidates_for_run,
    split_candidate_rows,
    _write_outputs,
)
from market_simulator.data.repository import MarketDataBundle
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.settings import DEFAULT_SUPPORTED_ETF_SYMBOLS, DEFAULT_SUPPORTED_REFERENCE_SERIES_SYMBOLS


def _supported_etfs() -> list[str]:
    return [symbol.strip() for symbol in DEFAULT_SUPPORTED_ETF_SYMBOLS.split(",")]


def _supported_reference_series() -> list[str]:
    return [symbol.strip() for symbol in DEFAULT_SUPPORTED_REFERENCE_SERIES_SYMBOLS.split(",")]


def _sample_candidate() -> CandidateConfig:
    return generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )[0]


def _sample_periods() -> list[PeriodSpec]:
    return build_split_periods("2018-01-02", "2024-12-31")


def _sample_metadata(periods: list[PeriodSpec] | None = None) -> dict:
    selected_periods = periods or _sample_periods()
    return build_evaluation_metadata(
        mode="smoke",
        start_date="2018-01-02",
        end_date="2024-12-31",
        periods=selected_periods,
    )


def _synthetic_row(candidate: CandidateConfig, *, suffix: str = "") -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "strategy_family": candidate.family,
        "strategy_name": candidate.config["name"],
        "symbol": candidate.config["tradable_symbol"],
        "benchmark": candidate.config["benchmark_symbol"],
        "candidate_category": "failed",
        "alpha_vs_tradable_buy_hold_pct": -1.0,
        "holdout_alpha_vs_tradable_buy_hold_pct": -0.5,
        "max_drawdown_pct": -12.0,
        "drawdown_delta_vs_tradable_buy_hold_pct": 0.5,
        "trade_count": 3,
        "score": -1.0,
        "gallery_ready": False,
        "gallery_ready_outperformance": False,
        "gallery_ready_defensive": False,
        "watchlist": False,
        "row_suffix": suffix,
    }


class FakeMarketDataRepo:
    def __init__(self):
        self.calls: list[dict] = []

    def get_market_data(self, tradable_symbol, reference_symbols, start_date, end_date):
        self.calls.append(
            {
                "tradable_symbol": tradable_symbol,
                "reference_symbols": list(reference_symbols),
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        dates = pd.date_range(start_date, end_date, freq="B")
        tradable = pd.DataFrame(
            {
                "date": dates[:2],
                "symbol": [tradable_symbol] * min(2, len(dates)),
                "close": [100.0, 101.0][: min(2, len(dates))],
            }
        )
        return MarketDataBundle(
            tradable=tradable,
            references={
                symbol: f"reference:{symbol}:{start_date}:{end_date}"
                for symbol in reference_symbols
            },
        )


class MultiSymbolMarketDataRepo:
    def __init__(self, closes: dict[str, list[float]]):
        self.closes = {symbol.upper(): values for symbol, values in closes.items()}

    def get_market_data(self, tradable_symbol, reference_symbols, start_date, end_date):
        dates = pd.date_range(start_date, periods=len(self.closes[tradable_symbol.upper()]), freq="B")
        return MarketDataBundle(
            tradable=pd.DataFrame(
                {
                    "date": dates,
                    "symbol": [tradable_symbol] * len(dates),
                    "close": self.closes[tradable_symbol.upper()],
                }
            ),
            references={},
        )


def _strategy_config_with_refs(reference_symbols: list[str], *, start_date: str = "2018-01-02") -> dict:
    config = json.loads(json.dumps(_sample_candidate().config))
    config["tradable_symbol"] = "QQQ"
    config["benchmark_symbol"] = "QQQ"
    config["reference_symbols"] = reference_symbols
    config["start_date"] = start_date
    config["end_date"] = "2024-12-31"
    config["entry_rule"] = {"kind": "atomic", "type": "rsi_below", "symbol": "QQQ", "lookback": 14, "threshold": 35}
    config["exit_rule"] = {"kind": "atomic", "type": "rsi_above", "symbol": "QQQ", "lookback": 14, "threshold": 65}
    return config


def test_candidate_config_generation_validates_strategy_v2_and_uses_supported_symbols():
    candidates = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="standard",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )

    assert len(candidates) >= 90
    assert {
        "core_rsi_overlay",
        "rsi_mean_reversion",
        "rsi_vix_regime_filter",
        "sma_trend_filter",
        "core_vix_trend_overlay",
        "defensive_relative_strength",
        "defensive_trend_filtered_pullback",
        "sector_relative_strength",
        "sector_core_relative_strength",
        "trend_pullback",
        "vix_trend_filter",
        "realized_volatility_filter",
        "asset_rotation_momentum",
        "sector_rotation_momentum",
        "defensive_rotation_momentum",
    } <= {candidate.family for candidate in candidates}

    supported = set(_supported_etfs()) | set(_supported_reference_series())
    for candidate in candidates:
        strategy = StrategyV2.model_validate(candidate.config)
        assert strategy.tradable_symbol in supported
        assert strategy.benchmark_symbol in supported
        assert set(strategy.reference_symbols) <= supported


def test_rank_candidate_rows_prefers_split_checked_candidates_over_one_window_accident():
    rows = [
        {
            "candidate_id": "one-window",
            "alpha_vs_benchmark_pct": 50,
            "earlier_alpha_vs_benchmark_pct": 40,
            "recent_alpha_vs_benchmark_pct": -10,
            "cagr_pct": 12,
            "sharpe_ratio": 1.2,
            "max_drawdown_pct": -20,
            "drawdown_delta_vs_benchmark_pct": -3,
            "trade_count_reasonable": True,
            "gallery_ready": False,
            "gallery_ready_outperformance": False,
            "gallery_ready_defensive": False,
            "watchlist": False,
            "max_drawdown_acceptable": True,
            "full_period_outperforms": True,
            "recent_period_outperforms": False,
            "split_period_outperforms_count": 1,
            "basic_sanity_pass": False,
        },
        {
            "candidate_id": "split-checked",
            "alpha_vs_benchmark_pct": 8,
            "earlier_alpha_vs_benchmark_pct": 3,
            "recent_alpha_vs_benchmark_pct": 4,
            "cagr_pct": 9,
            "sharpe_ratio": 0.9,
            "max_drawdown_pct": -14,
            "drawdown_delta_vs_benchmark_pct": 5,
            "trade_count_reasonable": True,
            "gallery_ready": True,
            "gallery_ready_outperformance": True,
            "gallery_ready_defensive": False,
            "watchlist": False,
            "max_drawdown_acceptable": True,
            "full_period_outperforms": True,
            "recent_period_outperforms": True,
            "split_period_outperforms_count": 2,
            "basic_sanity_pass": True,
        },
    ]

    ranked = rank_candidate_rows(rows)

    assert ranked[0]["candidate_id"] == "split-checked"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_split_period_labels_and_flags_are_basic_sanity_checks():
    periods = build_split_periods("2018-01-02", "2024-12-31")

    assert [period.label for period in periods] == ["full", "earlier", "recent_holdout"]
    assert periods[0].start_date == "2018-01-02"
    assert periods[0].end_date == "2024-12-31"
    assert periods[1].end_date < periods[2].start_date

    flags = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": 2.5,
            "max_drawdown_pct": -18,
            "drawdown_delta_vs_tradable_buy_hold_pct": 4,
            "trade_count": 8,
        },
        earlier_period={"alpha_vs_tradable_buy_hold_pct": -1.0},
        recent_period={"alpha_vs_tradable_buy_hold_pct": 3.0},
    )

    assert flags["gallery_ready"] is True
    assert flags["gallery_ready_outperformance"] is True
    assert flags["gallery_ready_defensive"] is False
    assert flags["watchlist"] is False
    assert flags["alpha_positive"] is True
    assert flags["recent_alpha_positive"] is True
    assert flags["drawdown_improvement_vs_benchmark"] is True
    assert flags["enough_trades"] is True
    assert flags["not_too_many_trades"] is True
    assert flags["full_period_outperforms"] is True
    assert flags["earlier_period_outperforms"] is False
    assert flags["recent_period_outperforms"] is True
    assert flags["split_period_outperforms_count"] == 1
    assert flags["max_drawdown_acceptable"] is True
    assert flags["trade_count_reasonable"] is True
    assert flags["basic_sanity_pass"] is True


def test_discovery_output_path_is_gitignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "data/discovery_reports/" in gitignore


def test_gallery_ready_requires_positive_alpha():
    flags = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": -0.1,
            "max_drawdown_pct": -10,
            "drawdown_delta_vs_tradable_buy_hold_pct": 5,
            "trade_count": 6,
        },
        earlier_period={"alpha_vs_tradable_buy_hold_pct": 1.0},
        recent_period={"alpha_vs_tradable_buy_hold_pct": 1.0},
    )

    assert flags["alpha_positive"] is False
    assert flags["gallery_ready_outperformance"] is False


def test_rotation_scoring_uses_universe_equal_weight_metrics_before_tradable_alpha():
    flags = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": -25.0,
            "alpha_vs_universe_equal_weight_pct": 3.5,
            "alpha_vs_market_benchmark_pct": -1.0,
            "max_drawdown_pct": -12,
            "drawdown_delta_vs_tradable_buy_hold_pct": -7,
            "drawdown_delta_vs_universe_equal_weight_pct": 4,
            "trade_count": 0,
            "rebalance_count": 8,
        },
        earlier_period={
            "alpha_vs_tradable_buy_hold_pct": -15.0,
            "alpha_vs_universe_equal_weight_pct": 1.0,
            "alpha_vs_market_benchmark_pct": -2.0,
        },
        recent_period={
            "alpha_vs_tradable_buy_hold_pct": -10.0,
            "alpha_vs_universe_equal_weight_pct": -2.0,
            "alpha_vs_market_benchmark_pct": 0.5,
        },
    )

    assert flags["benchmark_comparison_basis"] == "universe_equal_weight"
    assert flags["primary_alpha_pct"] == 3.5
    assert flags["holdout_primary_alpha_pct"] == 0.5
    assert flags["drawdown_improvement_vs_benchmark"] is True
    assert flags["trade_count_reasonable"] is True
    assert flags["gallery_ready_outperformance"] is True


def test_non_rotation_scoring_still_uses_tradable_buy_hold_metrics():
    flags = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": -0.1,
            "alpha_vs_market_benchmark_pct": 5.0,
            "max_drawdown_pct": -10,
            "drawdown_delta_vs_tradable_buy_hold_pct": 5,
            "trade_count": 6,
        },
        earlier_period={"alpha_vs_tradable_buy_hold_pct": 1.0},
        recent_period={"alpha_vs_tradable_buy_hold_pct": 1.0},
    )

    assert flags["benchmark_comparison_basis"] == "tradable_buy_hold"
    assert flags["primary_alpha_pct"] == -0.1
    assert flags["alpha_positive"] is False
    assert flags["gallery_ready_outperformance"] is False


def test_watchlist_can_include_near_miss_or_risk_improvement_candidate():
    near_miss = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": -1.5,
            "max_drawdown_pct": -9,
            "drawdown_delta_vs_tradable_buy_hold_pct": 6,
            "trade_count": 5,
        },
        earlier_period={"alpha_vs_tradable_buy_hold_pct": 0.5},
        recent_period={"alpha_vs_tradable_buy_hold_pct": -3.0},
    )

    assert near_miss["gallery_ready"] is False
    assert near_miss["watchlist"] is True
    assert near_miss["drawdown_improvement_vs_benchmark"] is True


def test_max_drawdown_helper_works_with_synthetic_equity_curve():
    drawdown = max_drawdown_pct_from_equity([100, 120, 90, 95, 130])

    assert drawdown == -25.0


def test_universe_equal_weight_buy_hold_helper_works_with_synthetic_data():
    loader = _MarketDataLoader(
        MultiSymbolMarketDataRepo(
            {
                "AAA": [100, 110, 120],
                "BBB": [100, 90, 80],
            }
        )
    )

    metrics = _universe_equal_weight_buy_hold_metrics(
        loader,
        universe=["AAA", "BBB"],
        start_date="2024-01-02",
        end_date="2024-01-04",
    )

    assert metrics["return_pct"] == 0
    assert metrics["max_drawdown_pct"] == 0


def test_report_split_files_are_created_with_synthetic_rows(tmp_path):
    config = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )[0].config
    candidate = CandidateConfig(
        candidate_id="synthetic-gallery-ready",
        family="synthetic",
        config_summary="Synthetic row",
        config=config,
    )
    ready_row = {
        "candidate_id": candidate.candidate_id,
        "strategy_family": "synthetic",
        "symbol": "QQQ",
        "benchmark": "QQQ",
        "candidate_category": "gallery_ready_outperformance",
        "alpha_vs_tradable_buy_hold_pct": 3.0,
        "holdout_alpha_vs_tradable_buy_hold_pct": 0.5,
        "max_drawdown_pct": -12,
        "tradable_buy_hold_max_drawdown_pct": -20,
        "drawdown_delta_vs_tradable_buy_hold_pct": 8,
        "trade_count": 4,
        "score": 10,
        "gallery_ready": True,
        "gallery_ready_outperformance": True,
        "gallery_ready_defensive": False,
        "watchlist": False,
    }
    paths = _write_outputs(
        run_dir=tmp_path,
        ranked_rows=[ready_row],
        failed_rows=[],
        candidates=[candidate],
        periods=[PeriodSpec("full", "2018-01-02", "2024-12-31")],
        top_n=5,
    )

    assert paths["gallery_ready_outperformance_csv"].exists()
    assert paths["gallery_ready_outperformance_json"].exists()
    assert paths["gallery_ready_defensive_csv"].exists()
    assert paths["watchlist_candidates_csv"].exists()
    assert paths["failed_candidates_csv"].exists()
    assert paths["top_by_alpha_vs_tradable_csv"].exists()
    assert paths["top_by_primary_alpha_csv"].exists()
    assert paths["top_by_drawdown_improvement_csv"].exists()
    assert paths["top_by_recent_alpha_csv"].exists()

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["gallery_ready_count"] == 1
    assert payload["gallery_ready_outperformance_count"] == 1
    assert payload["gallery_ready_defensive_count"] == 0
    assert payload["watchlist_count"] == 0
    assert payload["sanity_failed_count"] == 0
    assert payload["gallery_ready_outperformance"][0]["candidate_id"] == candidate.candidate_id


def test_no_candidates_passing_sanity_prints_no_gallery_ready_message(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/discover_gallery_candidates.py",
            "--start-date",
            "2018-01-02",
            "--end-date",
            "2024-12-31",
            "--max-candidates",
            "0",
            "--mode",
            "smoke",
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "No Gallery-ready candidates found." in result.stdout
    assert "Top Candidates" not in result.stdout
    summary = json.loads((tmp_path / "latest" / "candidate_summary.json").read_text(encoding="utf-8"))
    assert summary["gallery_ready_count"] == 0
    assert summary["watchlist_count"] == 0


def test_wrong_family_filter_exposes_available_family_names(tmp_path):
    result = run_discovery(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        output_dir=tmp_path,
        run_id="wrong-family",
        max_candidates=0,
        families={"not_a_real_family"},
    )

    summary = json.loads(
        (tmp_path / "wrong-family" / "candidate_summary.json").read_text(encoding="utf-8")
    )
    assert result["candidate_count"] == 0
    assert "not_a_real_family" in result["unmatched_families"]
    assert "available_families" in summary["run_metadata"]
    assert "rsi_mean_reversion" in summary["run_metadata"]["available_families"]


def test_split_candidate_rows_separates_gallery_watchlist_and_failed():
    rows = [
        {
            "candidate_id": "ready",
            "gallery_ready": True,
            "gallery_ready_outperformance": True,
            "gallery_ready_defensive": False,
            "watchlist": False,
        },
        {"candidate_id": "watch", "gallery_ready": False, "watchlist": True},
        {"candidate_id": "failed", "gallery_ready": False, "watchlist": False},
    ]

    split = split_candidate_rows(rows)

    assert [row["candidate_id"] for row in split["gallery_ready"]] == ["ready"]
    assert [row["candidate_id"] for row in split["gallery_ready_outperformance"]] == ["ready"]
    assert [row["candidate_id"] for row in split["watchlist"]] == ["watch"]
    assert [row["candidate_id"] for row in split["failed"]] == ["failed"]


def test_broad_candidate_generation_produces_valid_strategy_v2_configs():
    candidates = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="broad",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )

    assert len(candidates) > 1000
    assert len(candidates) == len({candidate.config_hash for candidate in candidates})
    for candidate in candidates[:250]:
        StrategyV2.model_validate(candidate.config)


def test_broad_rotation_generation_produces_richer_valid_strategy_v2_configs():
    candidates = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="broad",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )
    rotation_candidates = [
        candidate
        for candidate in candidates
        if candidate.config.get("rotation", {}).get("enabled")
    ]

    assert len(rotation_candidates) > 4
    assert {21, 63, 126, 252} <= {
        candidate.config["rotation"]["ranking"]["lookback"]
        for candidate in rotation_candidates
    }
    assert {"monthly", "quarterly"} <= {
        candidate.config["rotation"]["rebalance"]["frequency"]
        for candidate in rotation_candidates
    }
    assert {"cash", "asset"} <= {
        candidate.config["rotation"]["fallback"]["type"]
        for candidate in rotation_candidates
    }
    for candidate in rotation_candidates:
        StrategyV2.model_validate(candidate.config)


def test_duplicate_config_hashes_are_removed():
    base = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )[0]
    duplicate = CandidateConfig(
        candidate_id="duplicate",
        family=base.family,
        config_summary=base.config_summary,
        config={**base.config, "name": "Different display name"},
    )

    deduped = dedupe_candidate_configs([base, duplicate])

    assert len(deduped) == 1


def test_dual_benchmark_scoring_works_on_synthetic_metrics():
    scored = score_dual_benchmark_metrics(
        strategy_return_pct=12,
        strategy_max_drawdown_pct=-10,
        tradable_buy_hold_return_pct=8,
        tradable_buy_hold_max_drawdown_pct=-20,
        market_benchmark_symbol="SPY",
        market_benchmark_return_pct=6,
        market_benchmark_max_drawdown_pct=-15,
        universe_equal_weight_buy_hold_return_pct=9,
        universe_equal_weight_buy_hold_max_drawdown_pct=-18,
    )

    assert scored["alpha_vs_tradable_buy_hold_pct"] == 4
    assert scored["drawdown_delta_vs_tradable_buy_hold_pct"] == 10
    assert scored["alpha_vs_market_benchmark_pct"] == 6
    assert scored["drawdown_delta_vs_market_benchmark_pct"] == 5
    assert scored["alpha_vs_universe_equal_weight_pct"] == 3
    assert scored["drawdown_delta_vs_universe_equal_weight_pct"] == 8


def test_defensive_category_requires_drawdown_improvement_and_clear_label():
    defensive = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": -4,
            "max_drawdown_pct": -10,
            "drawdown_delta_vs_tradable_buy_hold_pct": 12,
            "trade_count": 6,
        },
        earlier_period={"alpha_vs_tradable_buy_hold_pct": -2},
        recent_period={"alpha_vs_tradable_buy_hold_pct": -3},
    )
    weak_drawdown = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": -4,
            "max_drawdown_pct": -10,
            "drawdown_delta_vs_tradable_buy_hold_pct": 2,
            "trade_count": 6,
        },
        earlier_period={"alpha_vs_tradable_buy_hold_pct": -2},
        recent_period={"alpha_vs_tradable_buy_hold_pct": -3},
    )

    assert defensive["gallery_ready_defensive"] is True
    assert defensive["gallery_ready_outperformance"] is False
    assert weak_drawdown["gallery_ready_defensive"] is False


def test_split_period_flags_work_on_synthetic_metrics():
    row_flags = build_candidate_flags(
        full_period={
            "alpha_vs_tradable_buy_hold_pct": 2,
            "max_drawdown_pct": -12,
            "drawdown_delta_vs_tradable_buy_hold_pct": 3,
            "trade_count": 4,
        },
        earlier_period={"alpha_vs_tradable_buy_hold_pct": 1},
        recent_period={"alpha_vs_tradable_buy_hold_pct": -0.5},
    )

    assert row_flags["gallery_ready_outperformance"] is True
    assert row_flags["split_period_outperforms_count"] == 1


def test_repeated_get_bundle_calls_with_same_key_call_repo_once():
    repo = FakeMarketDataRepo()
    loader = _MarketDataLoader(repo)
    strategy = StrategyV2.model_validate(_strategy_config_with_refs(["VIX", "IEF"]))

    first = loader.get_bundle(strategy)
    second = loader.get_bundle(strategy)

    assert first is second
    assert len(repo.calls) == 1
    assert loader.cache_stats()["bundle_cache_hits"] == 1
    assert loader.cache_stats()["bundle_cache_misses"] == 1


def test_reference_symbol_order_does_not_affect_bundle_cache_key():
    repo = FakeMarketDataRepo()
    loader = _MarketDataLoader(repo)
    first_strategy = StrategyV2.model_validate(_strategy_config_with_refs(["VIX", "IEF"]))
    second_strategy = StrategyV2.model_validate(_strategy_config_with_refs(["IEF", "VIX"]))

    loader.get_bundle(first_strategy)
    loader.get_bundle(second_strategy)

    assert len(repo.calls) == 1
    assert repo.calls[0]["reference_symbols"] == ["IEF", "VIX"]
    assert loader.cache_stats()["bundle_cache_hits"] == 1
    assert loader.cache_stats()["bundle_cache_misses"] == 1


def test_different_date_ranges_produce_different_bundle_cache_entries():
    repo = FakeMarketDataRepo()
    loader = _MarketDataLoader(repo)

    loader.get_bundle(StrategyV2.model_validate(_strategy_config_with_refs(["VIX"], start_date="2018-01-02")))
    loader.get_bundle(StrategyV2.model_validate(_strategy_config_with_refs(["VIX"], start_date="2019-01-02")))

    assert len(repo.calls) == 2
    assert loader.cache_stats()["bundle_cache_hits"] == 0
    assert loader.cache_stats()["bundle_cache_misses"] == 2


def test_different_reference_sets_produce_different_bundle_cache_entries():
    repo = FakeMarketDataRepo()
    loader = _MarketDataLoader(repo)

    loader.get_bundle(StrategyV2.model_validate(_strategy_config_with_refs(["VIX"])))
    loader.get_bundle(StrategyV2.model_validate(_strategy_config_with_refs(["IEF"])))

    assert len(repo.calls) == 2
    assert loader.cache_stats()["bundle_cache_misses"] == 2


def test_get_symbol_frame_cache_stats_still_work():
    repo = FakeMarketDataRepo()
    loader = _MarketDataLoader(repo)

    loader.get_symbol_frame("qqq", "2018-01-02", "2024-12-31")
    loader.get_symbol_frame("QQQ", "2018-01-02", "2024-12-31")
    loader.get_symbol_frame("SPY", "2018-01-02", "2024-12-31")

    stats = loader.cache_stats()
    assert len(repo.calls) == 2
    assert stats["symbol_frame_cache_hits"] == 1
    assert stats["symbol_frame_cache_misses"] == 2


def test_cache_miss_executes_candidate_and_writes_cache(tmp_path):
    candidate = _sample_candidate()
    periods = _sample_periods()
    calls = {"count": 0}

    def evaluator(next_candidate, next_periods, loader):
        calls["count"] += 1
        return _synthetic_row(next_candidate)

    result = evaluate_candidates_with_cache(
        candidates=[candidate],
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path,
        evaluation_metadata=_sample_metadata(periods),
        evaluator=evaluator,
    )

    cache_key = build_candidate_cache_key(
        candidate,
        periods=periods,
        evaluation_metadata=_sample_metadata(periods),
    )
    assert calls["count"] == 1
    assert result["executed"] == 1
    assert result["cache_hits"] == 0
    assert (tmp_path / f"{cache_key}.json").exists()


def test_cache_hit_with_resume_reuses_cached_result_without_execution(tmp_path):
    candidate = _sample_candidate()
    periods = _sample_periods()
    metadata = _sample_metadata(periods)

    evaluate_candidates_with_cache(
        candidates=[candidate],
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path,
        evaluation_metadata=metadata,
        evaluator=lambda next_candidate, next_periods, loader: _synthetic_row(next_candidate, suffix="cached"),
    )

    def should_not_execute(next_candidate, next_periods, loader):
        raise AssertionError("candidate should have been loaded from cache")

    result = evaluate_candidates_with_cache(
        candidates=[candidate],
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path,
        evaluation_metadata=metadata,
        evaluator=should_not_execute,
    )

    assert result["cache_hits"] == 1
    assert result["executed"] == 0
    assert result["rows"][0]["row_suffix"] == "cached"


def test_corrupt_cache_file_is_ignored_and_recomputed_with_warning(tmp_path, capsys):
    candidate = _sample_candidate()
    periods = _sample_periods()
    metadata = _sample_metadata(periods)
    cache_key = build_candidate_cache_key(candidate, periods=periods, evaluation_metadata=metadata)
    (tmp_path / f"{cache_key}.json").write_text("{not-json", encoding="utf-8")

    calls = {"count": 0}

    def evaluator(next_candidate, next_periods, loader):
        calls["count"] += 1
        return _synthetic_row(next_candidate, suffix="recomputed")

    result = evaluate_candidates_with_cache(
        candidates=[candidate],
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path,
        evaluation_metadata=metadata,
        evaluator=evaluator,
    )

    captured = capsys.readouterr()
    assert "Warning: ignoring corrupt discovery cache" in captured.out
    assert calls["count"] == 1
    assert result["rows"][0]["row_suffix"] == "recomputed"


def test_max_candidates_limits_selected_deterministic_candidates():
    candidates = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )

    selected = select_candidates_for_run(candidates, max_candidates=3)

    assert selected == candidates[:3]


def test_omitting_max_candidates_selects_all_generated_candidates():
    candidates = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )

    selected = select_candidates_for_run(candidates, max_candidates=None)

    assert selected == candidates


def test_cached_candidates_count_toward_max_candidates_but_are_skipped(tmp_path):
    candidates = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )
    selected = select_candidates_for_run(candidates, max_candidates=2)
    periods = _sample_periods()
    metadata = _sample_metadata(periods)

    evaluate_candidates_with_cache(
        candidates=[selected[0]],
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path,
        evaluation_metadata=metadata,
        evaluator=lambda next_candidate, next_periods, loader: _synthetic_row(next_candidate, suffix="first"),
    )

    calls: list[str] = []

    def evaluator(next_candidate, next_periods, loader):
        calls.append(next_candidate.candidate_id)
        return _synthetic_row(next_candidate, suffix="new")

    result = evaluate_candidates_with_cache(
        candidates=selected,
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path,
        evaluation_metadata=metadata,
        evaluator=evaluator,
    )

    assert result["selected_count"] == 2
    assert result["cache_hits"] == 1
    assert result["executed"] == 1
    assert calls == [selected[1].candidate_id]


def test_reports_include_cached_and_newly_executed_results(tmp_path):
    candidates = generate_candidate_configs(
        start_date="2018-01-02",
        end_date="2024-12-31",
        mode="smoke",
        supported_etfs=_supported_etfs(),
        supported_reference_series=_supported_reference_series(),
    )[:2]
    periods = _sample_periods()
    metadata = _sample_metadata(periods)

    evaluate_candidates_with_cache(
        candidates=[candidates[0]],
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path / "cache",
        evaluation_metadata=metadata,
        evaluator=lambda next_candidate, next_periods, loader: _synthetic_row(next_candidate, suffix="cached"),
    )
    result = evaluate_candidates_with_cache(
        candidates=candidates,
        periods=periods,
        loader=None,
        resume=True,
        cache_dir=tmp_path / "cache",
        evaluation_metadata=metadata,
        evaluator=lambda next_candidate, next_periods, loader: _synthetic_row(next_candidate, suffix="new"),
    )
    paths = _write_outputs(
        run_dir=tmp_path / "reports",
        ranked_rows=result["rows"],
        failed_rows=result["failed_rows"],
        candidates=candidates,
        periods=periods,
        top_n=5,
        run_metadata={
            "total_generated": len(candidates),
            "cache_hits": result["cache_hits"],
            "executed": result["executed"],
            "market_data_cache_stats": {
                "bundle_cache_hits": 3,
                "bundle_cache_misses": 2,
                "symbol_frame_cache_hits": 4,
                "symbol_frame_cache_misses": 5,
            },
        },
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    suffixes = {row["row_suffix"] for row in payload["results"]}
    assert suffixes == {"cached", "new"}
    assert payload["cache_hits"] == 1
    assert payload["executed"] == 1
    assert payload["run_metadata"]["market_data_cache_stats"]["bundle_cache_hits"] == 3
    assert payload["bundle_cache_hits"] == 3
    assert payload["symbol_frame_cache_misses"] == 5


def test_cache_key_changes_when_config_changes():
    candidate = _sample_candidate()
    variant_config = json.loads(json.dumps(candidate.config))
    variant_config["risk"]["cooldown_bars"] = variant_config["risk"]["cooldown_bars"] + 1
    variant = CandidateConfig(
        candidate_id="variant",
        family=candidate.family,
        config_summary=candidate.config_summary,
        config=variant_config,
    )
    periods = _sample_periods()
    metadata = _sample_metadata(periods)

    assert build_candidate_cache_key(candidate, periods=periods, evaluation_metadata=metadata) != (
        build_candidate_cache_key(variant, periods=periods, evaluation_metadata=metadata)
    )


def test_cache_key_changes_when_evaluation_window_settings_change():
    candidate = _sample_candidate()
    periods = _sample_periods()
    first_metadata = _sample_metadata(periods)
    second_periods = build_split_periods("2019-01-02", "2024-12-31")
    second_metadata = build_evaluation_metadata(
        mode="smoke",
        start_date="2019-01-02",
        end_date="2024-12-31",
        periods=second_periods,
    )

    assert build_candidate_cache_key(candidate, periods=periods, evaluation_metadata=first_metadata) != (
        build_candidate_cache_key(candidate, periods=second_periods, evaluation_metadata=second_metadata)
    )
