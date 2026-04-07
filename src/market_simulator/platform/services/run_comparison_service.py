from __future__ import annotations

from typing import Any

from market_simulator.platform.services.run_chart_service import RunChartService


class RunComparisonService:
    def __init__(self):
        self.chart_service = RunChartService()

    def build_comparison(self, runs: list[Any]) -> dict[str, Any]:
        run_summaries: list[dict[str, Any]] = []
        monthly_map: dict[str, dict[str, float | None]] = {}

        for run in runs:
            summary_json = run.summary_json or {}

            run_summaries.append(
                {
                    "run_id": str(run.id),
                    "strategy_id": str(run.strategy_id) if run.strategy_id else None,
                    "strategy_version_id": str(run.strategy_version_id) if run.strategy_version_id else None,
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

            if not run.artifact_manifest_json:
                continue

            chart_data = self.chart_service.load_chart_data(run.artifact_manifest_json)

            for row in chart_data["monthly_returns"]:
                month = row["month"]
                value = row["return_pct"]

                if month not in monthly_map:
                    monthly_map[month] = {}

                monthly_map[month][str(run.id)] = value

        monthly_returns = [
            {
                "month": month,
                "values": monthly_map[month],
            }
            for month in sorted(monthly_map.keys())
        ]

        return {
            "runs": run_summaries,
            "monthly_returns": monthly_returns,
        }

    def build_equity_curves(self, runs: list[Any]) -> dict:
        curves = []

        for run in runs:
            if not run.artifact_manifest_json:
                continue

            chart_data = self.chart_service.load_chart_data(run.artifact_manifest_json)

            points = [
                {
                    "date": row["date"],
                    "equity": row["strategy_equity"],
                }
                for row in chart_data["equity_curve"]
            ]

            curves.append(
                {
                    "run_id": str(run.id),
                    "points": points,
                }
            )

        return {"curves": curves}