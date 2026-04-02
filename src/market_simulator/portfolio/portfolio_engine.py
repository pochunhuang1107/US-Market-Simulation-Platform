from __future__ import annotations

import pandas as pd

from market_simulator.service import SimulationService
from .allocation import normalize_weights


def run_portfolio(portfolio_config, data_path=None, artifacts_dir=None):
    service = SimulationService(
        market_data_path=data_path,
        artifacts_dir=artifacts_dir,
    )

    strategies = normalize_weights(portfolio_config.strategies)

    equity_curves = []
    summaries = []

    for strat in strategies:
        result = service.run_from_file(strat.strategy_path)

        timeline = pd.DataFrame(result.timeline)
        timeline["weighted_equity"] = timeline["strategy_equity"] * strat.weight

        equity_curves.append(timeline[["date", "weighted_equity"]])

        summary = dict(result.summary)
        summary["strategy_name"] = strat.name
        summary["weight"] = strat.weight
        summaries.append(summary)

    merged = equity_curves[0]

    for df in equity_curves[1:]:
        merged = merged.merge(df, on="date", how="inner", suffixes=("", "_other"))
        merged["weighted_equity"] += merged.pop("weighted_equity_other")

    merged = merged.sort_values("date").reset_index(drop=True)

    merged["portfolio_equity"] = merged["weighted_equity"]

    total_return = (
        merged["portfolio_equity"].iloc[-1] / merged["portfolio_equity"].iloc[0] - 1
    ) * 100

    return {
        "timeline": merged,
        "summary": {
            "portfolio_total_return_pct": total_return,
            "strategy_count": len(strategies),
        },
        "strategy_summaries": summaries,
    }