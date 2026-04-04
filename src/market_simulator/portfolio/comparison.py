from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_simulator.models.portfolio import PortfolioConfig
from market_simulator.portfolio.portfolio_engine import run_portfolio


def run_portfolio_comparison(
    comparison_config_path: str,
    data_path: str | None = None,
    artifacts_dir: str | None = None,
):
    with open(comparison_config_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    comparison_name = payload["name"]
    portfolio_configs = payload["portfolio_configs"]

    base_dir = Path(artifacts_dir or "data/local_artifacts/portfolio_comparisons")
    comparison_dir = base_dir / comparison_name
    comparison_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    timeline_frames = []

    for item in portfolio_configs:
        config_path = item["config_path"]

        with open(config_path, "r", encoding="utf-8") as f:
            portfolio_cfg = PortfolioConfig(**json.load(f))

        result = run_portfolio(
            portfolio_config=portfolio_cfg,
            data_path=data_path,
            artifacts_dir=str(comparison_dir / "portfolio_runs"),
        )

        row = dict(result["summary"])
        row["portfolio_name"] = portfolio_cfg.name
        row["config_path"] = config_path
        row["artifact_dir"] = result["artifact_dir"]
        rows.append(row)

        timeline = result["timeline"].copy()
        if not isinstance(timeline, pd.DataFrame):
            timeline = pd.DataFrame(timeline)

        keep_cols = ["date", "portfolio_equity"]
        if "portfolio_benchmark_equity" in timeline.columns:
            keep_cols.append("portfolio_benchmark_equity")
        if "portfolio_drawdown_pct" in timeline.columns:
            keep_cols.append("portfolio_drawdown_pct")
        if "benchmark_drawdown_pct" in timeline.columns:
            keep_cols.append("benchmark_drawdown_pct")

        timeline = timeline[keep_cols].copy()
        rename_map = {
            "portfolio_equity": f"portfolio_equity__{portfolio_cfg.name}",
            "portfolio_benchmark_equity": f"portfolio_benchmark_equity__{portfolio_cfg.name}",
            "portfolio_drawdown_pct": f"portfolio_drawdown_pct__{portfolio_cfg.name}",
            "benchmark_drawdown_pct": f"benchmark_drawdown_pct__{portfolio_cfg.name}",
        }
        timeline = timeline.rename(columns={k: v for k, v in rename_map.items() if k in timeline.columns})
        timeline_frames.append(timeline)

    summary_df = pd.DataFrame(rows)

    sort_cols = []
    ascending = []
    if "portfolio_sharpe_ratio" in summary_df.columns:
        sort_cols.append("portfolio_sharpe_ratio")
        ascending.append(False)
    if "portfolio_max_drawdown_pct" in summary_df.columns:
        sort_cols.append("portfolio_max_drawdown_pct")
        ascending.append(True)

    if sort_cols:
        summary_df = summary_df.sort_values(by=sort_cols, ascending=ascending).reset_index(drop=True)

    merged_timeline = None
    for df in timeline_frames:
        if merged_timeline is None:
            merged_timeline = df.copy()
        else:
            merged_timeline = merged_timeline.merge(df, on="date", how="outer")

    if merged_timeline is None:
        merged_timeline = pd.DataFrame(columns=["date"])

    merged_timeline = merged_timeline.sort_values("date").reset_index(drop=True)

    summary_df.to_csv(comparison_dir / "portfolio_comparison_summary.csv", index=False)
    merged_timeline.to_csv(comparison_dir / "portfolio_comparison_timeline.csv", index=False)

    return {
        "comparison_dir": str(comparison_dir),
        "summary": summary_df,
        "timeline": merged_timeline,
    }