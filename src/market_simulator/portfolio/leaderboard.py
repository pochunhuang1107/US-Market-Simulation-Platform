from __future__ import annotations

import pandas as pd


def build_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    score = 0

    if "portfolio_sharpe_ratio" in df.columns:
        df["rank_sharpe"] = df["portfolio_sharpe_ratio"].rank(ascending=False)
        score += df["rank_sharpe"]

    if "portfolio_max_drawdown_pct" in df.columns:
        df["rank_drawdown"] = df["portfolio_max_drawdown_pct"].rank(ascending=True)
        score += df["rank_drawdown"]

    if "portfolio_cagr_pct" in df.columns:
        df["rank_cagr"] = df["portfolio_cagr_pct"].rank(ascending=False)
        score += df["rank_cagr"]

    if "alpha_vs_benchmark_pct" in df.columns:
        df["rank_alpha"] = df["alpha_vs_benchmark_pct"].rank(ascending=False)
        score += df["rank_alpha"]

    df["composite_score"] = score
    df = df.sort_values("composite_score", ascending=True).reset_index(drop=True)

    return df