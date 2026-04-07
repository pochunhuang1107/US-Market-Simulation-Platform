from __future__ import annotations

from typing import Any

from market_simulator.platform.services.run_chart_service import RunChartService


class RunComparisonService:
    def __init__(self):
        self.chart_service = RunChartService()

    def build_comparison(self, runs: list[Any]) -> dict[str, Any]:
        run_summaries: list[dict[str, Any]] = []

        for run in runs:
            summary_json = run.summary_json or {}

            run_summaries.append(
                {
                    "run_id": str(run.id),
                    "strategy_id": str(run.strategy_id) if run.strategy_id else None,
                    "strategy_version_id": str(run.strategy_version_id) if run.strategy_version_id else None,
                    "strategy_name": run.strategy.name if run.strategy else None,
                    "strategy_version_number": (
                        run.strategy_version.version_number if run.strategy_version else None
                    ),
                    "status": str(run.status),
                    "total_return_pct": summary_json.get("total_return_pct"),
                    "benchmark_return_pct": summary_json.get("benchmark_return_pct"),
                    "alpha_vs_benchmark_pct": summary_json.get("alpha_vs_benchmark_pct"),
                    "cagr_pct": summary_json.get("cagr_pct"),
                    "sharpe_ratio": summary_json.get("sharpe_ratio"),
                    "max_drawdown_pct": summary_json.get("max_drawdown_pct"),
                    "benchmark_max_drawdown_pct": summary_json.get("benchmark_max_drawdown_pct"),
                    "trade_count": summary_json.get("trade_count"),
                    "win_rate_pct": summary_json.get("win_rate_pct"),
                }
            )

        return {
            "runs": run_summaries,
        }

    def build_equity_curves(self, runs: list[Any]) -> dict:
        strategy_curves = []
        benchmark_curves = []
        strategy_drawdown_curves = []
        benchmark_drawdown_curves = []

        for run in runs:
            if not run.artifact_manifest_json:
                continue

            chart_data = self.chart_service.load_chart_data(run.artifact_manifest_json)

            label = None
            if getattr(run, "strategy", None) is not None:
                strategy_name = getattr(run.strategy, "name", None)
                if strategy_name:
                    label = strategy_name
                    if getattr(run, "strategy_version", None) is not None:
                        version_number = getattr(run.strategy_version, "version_number", None)
                        if version_number is not None:
                            label = f"{strategy_name} v{version_number}"
            if label is None:
                label = str(run.id)

            equity_rows = chart_data["equity_curve"]
            drawdown_rows = chart_data["drawdown_curve"]

            if equity_rows:
                first_strategy_equity = equity_rows[0]["strategy_equity"] or 0.0
                first_benchmark_equity = equity_rows[0].get("benchmark_equity") or 0.0
            else:
                first_strategy_equity = 0.0
                first_benchmark_equity = 0.0

            strategy_points = []
            benchmark_points = []

            for row in equity_rows:
                strategy_equity = row["strategy_equity"]
                benchmark_equity = row.get("benchmark_equity")

                normalized_strategy = (
                    round((strategy_equity / first_strategy_equity) * 100.0, 6)
                    if first_strategy_equity
                    else 100.0
                )

                strategy_points.append(
                    {
                        "date": row["date"],
                        "value": normalized_strategy,
                    }
                )

                if benchmark_equity is not None:
                    normalized_benchmark = (
                        round((benchmark_equity / first_benchmark_equity) * 100.0, 6)
                        if first_benchmark_equity
                        else 100.0
                    )
                    benchmark_points.append(
                        {
                            "date": row["date"],
                            "value": normalized_benchmark,
                        }
                    )

            strategy_drawdown_points = [
                {
                    "date": row["date"],
                    "value": row["strategy_drawdown_pct"],
                }
                for row in drawdown_rows
            ]

            benchmark_drawdown_points = [
                {
                    "date": row["date"],
                    "value": row["benchmark_drawdown_pct"],
                }
                for row in drawdown_rows
                if row.get("benchmark_drawdown_pct") is not None
            ]

            strategy_curves.append(
                {
                    "run_id": str(run.id),
                    "label": label,
                    "points": strategy_points,
                }
            )
            benchmark_curves.append(
                {
                    "run_id": str(run.id),
                    "label": label,
                    "points": benchmark_points,
                }
            )
            strategy_drawdown_curves.append(
                {
                    "run_id": str(run.id),
                    "label": label,
                    "points": strategy_drawdown_points,
                }
            )
            benchmark_drawdown_curves.append(
                {
                    "run_id": str(run.id),
                    "label": label,
                    "points": benchmark_drawdown_points,
                }
            )

        return {
            "strategy_curves": strategy_curves,
            "benchmark_curves": benchmark_curves,
            "strategy_drawdown_curves": strategy_drawdown_curves,
            "benchmark_drawdown_curves": benchmark_drawdown_curves,
        }