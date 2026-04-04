from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_simulator.service import SimulationService
from .allocation import normalize_weights
from .reporting import build_portfolio_monthly_returns, build_portfolio_summary


def run_portfolio(portfolio_config, data_path=None, artifacts_dir=None):
    artifacts_root = Path(artifacts_dir or "data/local_artifacts/portfolios")
    artifacts_root.mkdir(parents=True, exist_ok=True)

    portfolio_dir = artifacts_root / portfolio_config.name
    portfolio_dir.mkdir(parents=True, exist_ok=True)

    service = SimulationService(
        market_data_path=data_path,
        artifacts_dir=str(portfolio_dir / "strategy_runs"),
    )

    strategies = normalize_weights(portfolio_config.strategies)

    equity_curves = []
    summaries = []

    for strat in strategies:
        result = service.run_from_file(strat.strategy_path)

        timeline = pd.DataFrame(result.timeline).copy()
        if "benchmark_equity" in timeline.columns and "benchmark_equity_base" not in locals():
            benchmark_equity_base = timeline[["date", "benchmark_equity"]].copy()
        timeline["date"] = pd.to_datetime(timeline["date"])
        timeline = timeline.sort_values("date").reset_index(drop=True)

        first_equity = float(timeline["strategy_equity"].iloc[0])
        allocated_initial = float(portfolio_config.initial_capital) * float(strat.weight)

        timeline["weighted_equity"] = (
            timeline["strategy_equity"] / first_equity
        ) * allocated_initial

        equity_curves.append(
            timeline[["date", "weighted_equity"]].rename(
                columns={"weighted_equity": f"weighted_equity__{strat.name}"}
            )
        )

        summary = dict(result.summary)
        summary["strategy_name"] = strat.name
        summary["weight"] = strat.weight
        summary["artifact_dir"] = result.artifact_dir
        summaries.append(summary)

    merged = equity_curves[0].copy()

    for df in equity_curves[1:]:
        merged = merged.merge(df, on="date", how="inner")

    strategy_equity_cols = [c for c in merged.columns if c.startswith("weighted_equity__")]
    merged["portfolio_equity"] = merged[strategy_equity_cols].sum(axis=1)

    for col in strategy_equity_cols:
        contribution_col = col.replace("weighted_equity__", "contribution_pct__")
        merged[contribution_col] = merged[col] / merged["portfolio_equity"] * 100.0

    if "benchmark_equity_base" in locals():
        benchmark_equity_base = benchmark_equity_base.copy()
        benchmark_equity_base["date"] = pd.to_datetime(benchmark_equity_base["date"])
        benchmark_equity_base = benchmark_equity_base.sort_values("date").reset_index(drop=True)

        benchmark_first = float(benchmark_equity_base["benchmark_equity"].iloc[0])
        benchmark_equity_base["portfolio_benchmark_equity"] = (
            benchmark_equity_base["benchmark_equity"] / benchmark_first
        ) * float(portfolio_config.initial_capital)

        merged = merged.merge(
            benchmark_equity_base[["date", "portfolio_benchmark_equity"]],
            on="date",
            how="left",
        )

    merged["portfolio_cummax"] = merged["portfolio_equity"].cummax()
    merged["portfolio_drawdown_pct"] = (
        merged["portfolio_equity"] / merged["portfolio_cummax"] - 1.0
    ) * 100.0

    if "portfolio_benchmark_equity" in merged.columns:
        merged["benchmark_cummax"] = merged["portfolio_benchmark_equity"].cummax()
        merged["benchmark_drawdown_pct"] = (
            merged["portfolio_benchmark_equity"] / merged["benchmark_cummax"] - 1.0
        ) * 100.0

    portfolio_summary = build_portfolio_summary(merged)
    monthly_returns = build_portfolio_monthly_returns(merged)

    merged_out = merged.copy()
    merged_out["date"] = merged_out["date"].dt.strftime("%Y-%m-%d")

    merged_out.to_csv(portfolio_dir / "portfolio_timeline.csv", index=False)
    monthly_returns.to_csv(portfolio_dir / "portfolio_monthly_returns.csv", index=False)

    (portfolio_dir / "portfolio_summary.json").write_text(
        json.dumps(portfolio_summary, indent=2),
        encoding="utf-8",
    )

    (portfolio_dir / "strategy_summaries.json").write_text(
        json.dumps(summaries, indent=2),
        encoding="utf-8",
    )

    return {
        "timeline": merged_out,
        "summary": portfolio_summary,
        "strategy_summaries": summaries,
        "artifact_dir": str(portfolio_dir),
    }