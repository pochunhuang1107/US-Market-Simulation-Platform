from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _max_consecutive(values, target=True) -> int:
    best = 0
    cur = 0
    for v in values:
        if bool(v) == target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def build_trade_analytics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "closed_trade_count": 0,
            "winning_trade_count": 0,
            "losing_trade_count": 0,
            "profit_factor": None,
            "avg_win": None,
            "avg_loss": None,
            "payoff_ratio": None,
            "best_trade": None,
            "worst_trade": None,
        }

    pnl_col = "net_pnl" if "net_pnl" in trades.columns else None
    if pnl_col is None:
        return {
            "closed_trade_count": 0,
            "winning_trade_count": 0,
            "losing_trade_count": 0,
            "profit_factor": None,
            "avg_win": None,
            "avg_loss": None,
            "payoff_ratio": None,
            "best_trade": None,
            "worst_trade": None,
        }

    closed = trades[trades[pnl_col].notna()].copy()
    if closed.empty:
        return {
            "closed_trade_count": 0,
            "winning_trade_count": 0,
            "losing_trade_count": 0,
            "profit_factor": None,
            "avg_win": None,
            "avg_loss": None,
            "payoff_ratio": None,
            "best_trade": None,
            "worst_trade": None,
        }

    wins = closed[closed[pnl_col] > 0]
    losses = closed[closed[pnl_col] < 0]

    gross_profit = wins[pnl_col].sum() if not wins.empty else 0.0
    gross_loss = abs(losses[pnl_col].sum()) if not losses.empty else 0.0

    avg_win = wins[pnl_col].mean() if not wins.empty else None
    avg_loss = abs(losses[pnl_col].mean()) if not losses.empty else None

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    payoff_ratio = (avg_win / avg_loss) if avg_win is not None and avg_loss not in (None, 0) else None

    return {
        "closed_trade_count": int(len(closed)),
        "winning_trade_count": int(len(wins)),
        "losing_trade_count": int(len(losses)),
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
        "avg_win": round(float(avg_win), 6) if avg_win is not None else None,
        "avg_loss": round(float(avg_loss), 6) if avg_loss is not None else None,
        "payoff_ratio": round(payoff_ratio, 6) if payoff_ratio is not None else None,
        "best_trade": round(float(closed[pnl_col].max()), 6),
        "worst_trade": round(float(closed[pnl_col].min()), 6),
    }


def build_timeline_analytics(timeline: pd.DataFrame) -> dict:
    if timeline.empty:
        return {
            "time_in_market_pct": None,
            "avg_exposure_pct": None,
            "max_consecutive_days_in_market": 0,
            "final_core_weight_pct": None,
            "final_overlay_weight_pct": None,
        }

    shares_col = "overlay_position_shares" if "overlay_position_shares" in timeline.columns else None
    overlay_weight_col = "overlay_weight_pct" if "overlay_weight_pct" in timeline.columns else None
    core_weight_col = "core_weight_pct" if "core_weight_pct" in timeline.columns else None

    in_market = []
    if shares_col is not None:
        in_market = (timeline[shares_col] > 0).tolist()

    time_in_market_pct = None
    avg_exposure_pct = None
    max_consecutive_days_in_market = 0

    if in_market:
        time_in_market_pct = 100.0 * (sum(in_market) / len(in_market))
        max_consecutive_days_in_market = _max_consecutive(in_market, True)

    if overlay_weight_col is not None:
        avg_exposure_pct = float(timeline[overlay_weight_col].mean())

    final_core_weight_pct = None
    final_overlay_weight_pct = None

    if core_weight_col is not None:
        final_core_weight_pct = float(timeline[core_weight_col].iloc[-1])

    if overlay_weight_col is not None:
        final_overlay_weight_pct = float(timeline[overlay_weight_col].iloc[-1])

    return {
        "time_in_market_pct": round(time_in_market_pct, 6) if time_in_market_pct is not None else None,
        "avg_exposure_pct": round(avg_exposure_pct, 6) if avg_exposure_pct is not None else None,
        "max_consecutive_days_in_market": int(max_consecutive_days_in_market),
        "final_core_weight_pct": round(final_core_weight_pct, 6) if final_core_weight_pct is not None else None,
        "final_overlay_weight_pct": round(final_overlay_weight_pct, 6) if final_overlay_weight_pct is not None else None,
    }


def build_monthly_return_table(timeline: pd.DataFrame) -> pd.DataFrame:
    if timeline.empty:
        return pd.DataFrame(columns=["month", "strategy_return_pct", "benchmark_return_pct"])

    df = timeline.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)

    monthly = (
        df.groupby("month")
        .agg(
            strategy_start=("strategy_equity", "first"),
            strategy_end=("strategy_equity", "last"),
            benchmark_start=("benchmark_equity", "first"),
            benchmark_end=("benchmark_equity", "last"),
        )
        .reset_index()
    )

    monthly["strategy_return_pct"] = (
        (monthly["strategy_end"] / monthly["strategy_start"] - 1.0) * 100.0
    )
    monthly["benchmark_return_pct"] = (
        (monthly["benchmark_end"] / monthly["benchmark_start"] - 1.0) * 100.0
    )

    return monthly[["month", "strategy_return_pct", "benchmark_return_pct"]].round(6)


def build_report_bundle(summary: dict, trades: pd.DataFrame, timeline: pd.DataFrame) -> dict:
    trade_analytics = build_trade_analytics(trades)
    timeline_analytics = build_timeline_analytics(timeline)

    return {
        "summary": summary,
        "trade_analytics": trade_analytics,
        "timeline_analytics": timeline_analytics,
    }