from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _safe_float(x: Any) -> float | None:
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def build_portfolio_summary(timeline: pd.DataFrame) -> dict:
    if timeline.empty:
        return {
            "portfolio_total_return_pct": None,
            "portfolio_cagr_pct": None,
            "portfolio_max_drawdown_pct": None,
            "portfolio_sharpe_ratio": None,
            "start_equity": None,
            "end_equity": None,
            "benchmark_end_equity": None,
            "benchmark_return_pct": None,
            "alpha_vs_benchmark_pct": None,
            "trading_days": 0,
        }

    df = timeline.copy()
    df = df.sort_values("date").reset_index(drop=True)

    start_equity = float(df["portfolio_equity"].iloc[0])
    end_equity = float(df["portfolio_equity"].iloc[-1])
    trading_days = int(len(df))

    benchmark_end_equity = None
    if "portfolio_benchmark_equity" in df.columns:
        benchmark_end_equity = float(df["portfolio_benchmark_equity"].iloc[-1])

    total_return_pct = ((end_equity / start_equity) - 1.0) * 100.0

    benchmark_return_pct = None
    alpha_vs_benchmark_pct = None
    if benchmark_end_equity is not None and start_equity > 0:
        benchmark_return_pct = ((benchmark_end_equity / start_equity) - 1.0) * 100.0
        alpha_vs_benchmark_pct = total_return_pct - benchmark_return_pct

    years = trading_days / 252.0
    cagr_pct = None
    if years > 0 and start_equity > 0:
        cagr_pct = ((end_equity / start_equity) ** (1.0 / years) - 1.0) * 100.0

    df["daily_return"] = df["portfolio_equity"].pct_change().fillna(0.0)

    sharpe_ratio = None
    daily_std = df["daily_return"].std()
    if daily_std and not pd.isna(daily_std) and daily_std > 0:
        sharpe_ratio = (df["daily_return"].mean() / daily_std) * math.sqrt(252)

    df["cummax"] = df["portfolio_equity"].cummax()
    df["drawdown_pct"] = (df["portfolio_equity"] / df["cummax"] - 1.0) * 100.0
    max_drawdown_pct = float(df["drawdown_pct"].min())

    return {
        "portfolio_total_return_pct": round(total_return_pct, 6),
        "portfolio_cagr_pct": round(cagr_pct, 6) if cagr_pct is not None else None,
        "portfolio_max_drawdown_pct": round(max_drawdown_pct, 6),
        "portfolio_sharpe_ratio": round(float(sharpe_ratio), 6) if sharpe_ratio is not None else None,
        "start_equity": round(start_equity, 6),
        "end_equity": round(end_equity, 6),
        "benchmark_end_equity": round(benchmark_end_equity, 6) if benchmark_end_equity is not None else None,
        "benchmark_return_pct": round(benchmark_return_pct, 6) if benchmark_return_pct is not None else None,
        "alpha_vs_benchmark_pct": round(alpha_vs_benchmark_pct, 6) if alpha_vs_benchmark_pct is not None else None,
        "trading_days": trading_days,
    }


def build_portfolio_monthly_returns(timeline: pd.DataFrame) -> pd.DataFrame:
    if timeline.empty:
        return pd.DataFrame(columns=["month", "portfolio_return_pct"])

    df = timeline.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)

    monthly = (
        df.groupby("month")
        .agg(
            start_equity=("portfolio_equity", "first"),
            end_equity=("portfolio_equity", "last"),
        )
        .reset_index()
    )

    monthly["portfolio_return_pct"] = (
        (monthly["end_equity"] / monthly["start_equity"] - 1.0) * 100.0
    )

    return monthly[["month", "portfolio_return_pct"]].round(6)