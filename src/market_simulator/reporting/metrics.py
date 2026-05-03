from __future__ import annotations

import math

import pandas as pd

TRADING_DAYS = 252

FULL_EXIT_ACTIONS = {
    "SELL_ALL",
    "SELL_ALL_EXIT_SIGNAL",
    "SELL_ALL_STOP_LOSS",
    "SELL_ALL_TAKE_PROFIT",
}


def _trade_activity_counts(trades: pd.DataFrame) -> dict[str, int]:
    if trades.empty or "action" not in trades.columns:
        return {
            "trade_event_count": 0,
            "full_exit_count": 0,
            "buy_event_count": 0,
            "entry_event_count": 0,
            "add_event_count": 0,
            "reduce_event_count": 0,
        }

    actions = trades["action"].astype(str)
    return {
        "trade_event_count": int(len(trades)),
        "full_exit_count": int(actions.isin(FULL_EXIT_ACTIONS).sum()),
        "buy_event_count": int((actions == "BUY").sum()),
        "entry_event_count": int((actions == "BUY").sum()),
        "add_event_count": int((actions == "BUY_ADD").sum()),
        "reduce_event_count": int(
            actions.isin({"SELL_REDUCE", "SELL_REDUCE_PROFIT"}).sum()
        ),
    }


def build_summary(timeline: pd.DataFrame, trades: pd.DataFrame, strategy):
    initial = strategy.initial_capital
    ending = float(timeline["strategy_equity"].iloc[-1])
    ending_b = float(timeline["benchmark_equity"].iloc[-1])
    total = ending / initial - 1.0
    bench = ending_b / initial - 1.0

    dr = timeline["strategy_equity"].pct_change().dropna()
    sharpe = (
        (dr.mean() / dr.std(ddof=1)) * math.sqrt(TRADING_DAYS)
        if len(dr) > 1 and dr.std(ddof=1) > 0
        else 0.0
    )

    rm = timeline["strategy_equity"].cummax()
    max_dd = float((timeline["strategy_equity"] / rm - 1.0).min())

    brm = timeline["benchmark_equity"].cummax()
    bdd = float((timeline["benchmark_equity"] / brm - 1.0).min())

    start = pd.to_datetime(timeline["date"].iloc[0])
    end = pd.to_datetime(timeline["date"].iloc[-1])
    years = max((end - start).days / 365.25, 0.0001)
    cagr = (ending / initial) ** (1 / years) - 1

    exits = trades[trades["action"].isin(FULL_EXIT_ACTIONS)] if not trades.empty else trades
    win = float((exits["net_pnl"] > 0).mean()) if not exits.empty else 0.0
    activity_counts = _trade_activity_counts(trades)

    return {
        "name": strategy.name,
        "tradable_symbol": strategy.tradable_symbol,
        "benchmark_symbol": strategy.benchmark_symbol,
        "start_date": str(start.date()),
        "end_date": str(end.date()),
        "initial_capital": round(initial, 6),
        "ending_equity": round(ending, 6),
        "ending_benchmark_equity": round(ending_b, 6),
        "total_return_pct": round(total * 100, 4),
        "benchmark_return_pct": round(bench * 100, 4),
        "alpha_vs_benchmark_pct": round((total - bench) * 100, 4),
        "cagr_pct": round(cagr * 100, 4),
        "sharpe_ratio": round(float(sharpe), 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "benchmark_max_drawdown_pct": round(bdd * 100, 4),
        "trade_count": int(len(exits)),
        **activity_counts,
        "win_rate_pct": round(win * 100, 4),
        "final_cash": round(float(timeline["cash"].iloc[-1]), 6),
        "final_core_cash": round(float(timeline["core_cash"].iloc[-1]), 6),
        "final_overlay_cash": round(float(timeline["overlay_cash"].iloc[-1]), 6),
    }


def build_sleeve_summary(timeline: pd.DataFrame):
    initial_total = float(timeline["strategy_equity"].iloc[0])

    core_initial = float(timeline["core_equity"].iloc[0])
    core_ending = float(timeline["core_equity"].iloc[-1])

    overlay_initial = float(timeline["overlay_equity"].iloc[0])
    overlay_ending = float(timeline["overlay_equity"].iloc[-1])

    core_pnl = core_ending - core_initial
    overlay_pnl = overlay_ending - overlay_initial
    total_pnl = core_pnl + overlay_pnl

    return {
        "core_initial_equity": round(core_initial, 6),
        "core_ending_equity": round(core_ending, 6),
        "core_return_pct": round(((core_ending / core_initial) - 1.0) * 100, 4) if core_initial else 0.0,
        "core_pnl": round(core_pnl, 6),
        "core_contribution_to_total_return_pct": round((core_pnl / initial_total) * 100, 4) if initial_total else 0.0,
        "overlay_initial_equity": round(overlay_initial, 6),
        "overlay_ending_equity": round(overlay_ending, 6),
        "overlay_return_pct": round(((overlay_ending / overlay_initial) - 1.0) * 100, 4) if overlay_initial else 0.0,
        "overlay_pnl": round(overlay_pnl, 6),
        "overlay_contribution_to_total_return_pct": round((overlay_pnl / initial_total) * 100, 4) if initial_total else 0.0,
        "core_share_of_total_pnl_pct": round((core_pnl / total_pnl) * 100, 4) if total_pnl else 0.0,
        "overlay_share_of_total_pnl_pct": round((overlay_pnl / total_pnl) * 100, 4) if total_pnl else 0.0,
    }


def build_yearly_report(timeline: pd.DataFrame):
    df = timeline.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year

    out = []
    for year, grp in df.groupby("year"):
        se = float(grp["strategy_equity"].iloc[0])
        ee = float(grp["strategy_equity"].iloc[-1])
        sr = ee / se - 1.0 if se else 0.0

        sb = float(grp["benchmark_equity"].iloc[0])
        eb = float(grp["benchmark_equity"].iloc[-1])
        br = eb / sb - 1.0 if sb else 0.0

        rm = grp["strategy_equity"].cummax()
        dd = float((grp["strategy_equity"] / rm - 1.0).min())

        core_start = float(grp["core_equity"].iloc[0])
        core_end = float(grp["core_equity"].iloc[-1])
        core_return = core_end / core_start - 1.0 if core_start else 0.0

        overlay_start = float(grp["overlay_equity"].iloc[0])
        overlay_end = float(grp["overlay_equity"].iloc[-1])
        overlay_return = overlay_end / overlay_start - 1.0 if overlay_start else 0.0

        total_start = se
        core_contrib = (core_end - core_start) / total_start if total_start else 0.0
        overlay_contrib = (overlay_end - overlay_start) / total_start if total_start else 0.0

        out.append({
            "year": int(year),
            "start_equity": round(se, 6),
            "end_equity": round(ee, 6),
            "strategy_return_pct": round(sr * 100, 4),
            "benchmark_return_pct": round(br * 100, 4),
            "alpha_vs_benchmark_pct": round((sr - br) * 100, 4),
            "max_drawdown_pct": round(dd * 100, 4),
            "core_start_equity": round(core_start, 6),
            "core_end_equity": round(core_end, 6),
            "core_return_pct": round(core_return * 100, 4),
            "overlay_start_equity": round(overlay_start, 6),
            "overlay_end_equity": round(overlay_end, 6),
            "overlay_return_pct": round(overlay_return * 100, 4),
            "core_contribution_to_total_return_pct": round(core_contrib * 100, 4),
            "overlay_contribution_to_total_return_pct": round(overlay_contrib * 100, 4),
        })

    return out

def build_overlay_diagnostics(timeline: pd.DataFrame, trades: pd.DataFrame):
    if timeline.empty:
        return {}

    df = timeline.copy()

    # time in market
    in_position = df["overlay_position_shares"] > 0
    pct_time_in_market = in_position.mean()

    # capital usage
    total_overlay_equity = df["overlay_equity"]
    deployed = df["overlay_position_market_value"]
    pct_capital_deployed = (
        (deployed / total_overlay_equity.replace(0, 1)).mean()
    )

    # trade stats
    exits = trades[trades["action"].isin(FULL_EXIT_ACTIONS)] if not trades.empty else trades

    avg_win = float(exits[exits["net_pnl"] > 0]["net_pnl"].mean()) if not exits.empty else 0.0
    avg_loss = float(exits[exits["net_pnl"] < 0]["net_pnl"].mean()) if not exits.empty else 0.0

    win_rate = float((exits["net_pnl"] > 0).mean()) if not exits.empty else 0.0

    # exit reasons
    exit_counts = exits["action"].value_counts().to_dict() if not exits.empty else {}

    return {
        "pct_time_in_market": round(pct_time_in_market * 100, 4),
        "avg_capital_deployed_pct": round(pct_capital_deployed * 100, 4),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "win_rate_pct": round(win_rate * 100, 4),
        "exit_reason_counts": exit_counts,
    }
