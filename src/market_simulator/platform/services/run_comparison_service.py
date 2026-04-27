from __future__ import annotations

import math
from datetime import date
from statistics import stdev
from typing import Any

from market_simulator.platform.services.run_chart_service import RunChartService

FULL_PERIOD_METRICS = "FULL_PERIOD_METRICS"
COMMON_OVERLAP_METRICS = "COMMON_OVERLAP_METRICS"
FULL_PERIOD_CHART = "FULL_PERIOD"
COMMON_OVERLAP_CHART = "COMMON_OVERLAP"

BENCHMARK_SYMBOL_KEYS = ("benchmark_symbol", "benchmark_ticker", "benchmark")
BENCHMARK_NAME_KEYS = ("benchmark_name", "benchmark_label")


class RunComparisonService:
    def __init__(self):
        self.chart_service = RunChartService()

    def _clean_benchmark_value(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None

        cleaned = value.strip()
        return cleaned or None

    def _find_benchmark_value(self, source: Any, keys: tuple[str, ...]) -> str | None:
        if not isinstance(source, dict):
            return None

        for key in keys:
            value = self._clean_benchmark_value(source.get(key))
            if value is not None:
                return value

        return None

    def _extract_benchmark_label(
        self,
        run: Any,
        chart_data: dict[str, Any] | None = None,
    ) -> str | None:
        request_payload = run.request_payload or {}
        summary_json = run.summary_json or {}
        draft_config = request_payload.get("draft_config") if isinstance(request_payload, dict) else None
        version_config = (
            run.strategy_version.config_json
            if getattr(run, "strategy_version", None) is not None
            else None
        )

        sources = [
            summary_json,
            request_payload,
            draft_config,
            version_config,
            chart_data,
        ]

        for source in sources:
            symbol = self._find_benchmark_value(source, BENCHMARK_SYMBOL_KEYS)
            if symbol is not None:
                return symbol.upper()

            name = self._find_benchmark_value(source, BENCHMARK_NAME_KEYS)
            if name is not None:
                return name

        return None

    def _build_run_window(self, run: Any) -> dict[str, str | None]:
        window = {
            "run_id": str(run.id),
            "start_date": None,
            "end_date": None,
        }

        if not run.artifact_manifest_json:
            return window

        chart_data = self._load_chart_data(run.artifact_manifest_json)
        if chart_data is None:
            return window

        equity_rows = chart_data.get("equity_curve") or []
        if not equity_rows:
            return window

        start_date = equity_rows[0].get("date")
        end_date = equity_rows[-1].get("date")
        if not start_date or not end_date:
            return window

        return {
            "run_id": str(run.id),
            "start_date": str(start_date),
            "end_date": str(end_date),
        }

    def _build_run_window_from_chart_data(
        self,
        run: Any,
        chart_data: dict[str, Any] | None,
    ) -> dict[str, str | None]:
        window = {
            "run_id": str(run.id),
            "start_date": None,
            "end_date": None,
        }
        if chart_data is None:
            return window

        equity_rows = chart_data.get("equity_curve") or []
        if not equity_rows:
            return window

        start_date = equity_rows[0].get("date")
        end_date = equity_rows[-1].get("date")
        if not start_date or not end_date:
            return window

        return {
            "run_id": str(run.id),
            "start_date": str(start_date),
            "end_date": str(end_date),
        }

    def _load_chart_data(self, artifact_manifest_json: dict[str, str]) -> dict[str, Any] | None:
        try:
            return self.chart_service.load_chart_data(artifact_manifest_json)
        except Exception:
            return None

    def _load_chart_data_by_run_id(self, runs: list[Any]) -> dict[str, dict[str, Any]]:
        chart_data_by_run_id: dict[str, dict[str, Any]] = {}

        for run in runs:
            if not run.artifact_manifest_json:
                continue

            chart_data = self._load_chart_data(run.artifact_manifest_json)
            if chart_data is not None:
                chart_data_by_run_id[str(run.id)] = chart_data

        return chart_data_by_run_id

    def _build_window_metadata(
        self,
        runs: list[Any],
        chart_data_by_run_id: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if chart_data_by_run_id is None:
            run_windows = [self._build_run_window(run) for run in runs]
        else:
            run_windows = [
                self._build_run_window_from_chart_data(run, chart_data_by_run_id.get(str(run.id)))
                for run in runs
            ]
        available_windows = [
            window
            for window in run_windows
            if window["start_date"] is not None and window["end_date"] is not None
        ]

        overlap_start = None
        overlap_end = None
        has_common_overlap = False

        if available_windows:
            overlap_start = max(str(window["start_date"]) for window in available_windows)
            overlap_end = min(str(window["end_date"]) for window in available_windows)
            has_common_overlap = overlap_start <= overlap_end

        distinct_windows = {
            (window["start_date"], window["end_date"])
            for window in available_windows
        }
        has_missing_windows = len(available_windows) != len(run_windows)
        windows_differ = len(distinct_windows) > 1

        warning_message = None
        window_mode = FULL_PERIOD_METRICS
        if available_windows and not has_common_overlap:
            warning_message = (
                "Selected runs do not have a common comparison window. "
                "Metrics are still full-period run metrics."
            )
        elif windows_differ and has_common_overlap and not has_missing_windows:
            window_mode = COMMON_OVERLAP_METRICS
        elif windows_differ:
            warning_message = "Selected runs use different date ranges."
        elif has_missing_windows:
            warning_message = (
                "One or more selected run date ranges could not be inferred from chart artifacts. "
                "Metrics are still full-period run metrics."
            )

        return {
            "run_windows": run_windows,
            "overlap_start": overlap_start,
            "overlap_end": overlap_end,
            "has_common_overlap": has_common_overlap,
            "window_mode": window_mode,
            "warning_message": warning_message,
        }

    def _build_full_period_run_summary(self, run: Any) -> dict[str, Any]:
        summary_json = run.summary_json or {}

        return {
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

    def _parse_date(self, value: Any) -> date | None:
        if value is None:
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def _pct_return(self, start_value: Any, end_value: Any) -> float | None:
        if not isinstance(start_value, (int, float)) or not isinstance(end_value, (int, float)):
            return None
        if not math.isfinite(start_value) or not math.isfinite(end_value) or start_value == 0:
            return None
        return round(((end_value / start_value) - 1.0) * 100.0, 6)

    def _cagr_pct(
        self,
        start_value: Any,
        end_value: Any,
        start_date: Any,
        end_date: Any,
    ) -> float | None:
        if not isinstance(start_value, (int, float)) or not isinstance(end_value, (int, float)):
            return None
        if start_value <= 0 or end_value <= 0:
            return None

        parsed_start = self._parse_date(start_date)
        parsed_end = self._parse_date(end_date)
        if parsed_start is None or parsed_end is None:
            return None

        day_count = (parsed_end - parsed_start).days
        if day_count <= 0:
            return None

        return round((((end_value / start_value) ** (365.25 / day_count)) - 1.0) * 100.0, 6)

    def _sharpe_ratio(self, equity_rows: list[dict[str, Any]]) -> float | None:
        returns: list[float] = []

        for previous, current in zip(equity_rows, equity_rows[1:]):
            previous_equity = previous.get("strategy_equity")
            current_equity = current.get("strategy_equity")
            if (
                not isinstance(previous_equity, (int, float))
                or not isinstance(current_equity, (int, float))
                or previous_equity <= 0
            ):
                continue

            daily_return = (current_equity / previous_equity) - 1.0
            if math.isfinite(daily_return):
                returns.append(daily_return)

        if len(returns) < 2:
            return None

        volatility = stdev(returns)
        if volatility == 0:
            return None

        return round((sum(returns) / len(returns)) / volatility * math.sqrt(252.0), 6)

    def _build_overlap_run_summary(
        self,
        run: Any,
        chart_data: dict[str, Any] | None,
        overlap_start: str,
        overlap_end: str,
    ) -> dict[str, Any]:
        run_summary = self._build_full_period_run_summary(run)
        equity_rows = [
            row
            for row in (chart_data or {}).get("equity_curve", [])
            if overlap_start <= str(row.get("date")) <= overlap_end
        ]
        drawdown_rows = [
            row
            for row in (chart_data or {}).get("drawdown_curve", [])
            if overlap_start <= str(row.get("date")) <= overlap_end
        ]

        total_return_pct = None
        benchmark_return_pct = None
        cagr_pct = None
        sharpe_ratio = None
        if len(equity_rows) >= 2:
            first_row = equity_rows[0]
            last_row = equity_rows[-1]
            total_return_pct = self._pct_return(
                first_row.get("strategy_equity"),
                last_row.get("strategy_equity"),
            )
            benchmark_return_pct = self._pct_return(
                first_row.get("benchmark_equity"),
                last_row.get("benchmark_equity"),
            )
            cagr_pct = self._cagr_pct(
                first_row.get("strategy_equity"),
                last_row.get("strategy_equity"),
                first_row.get("date"),
                last_row.get("date"),
            )
            sharpe_ratio = self._sharpe_ratio(equity_rows)

        strategy_drawdowns = [
            row.get("strategy_drawdown_pct")
            for row in drawdown_rows
            if isinstance(row.get("strategy_drawdown_pct"), (int, float))
        ]
        benchmark_drawdowns = [
            row.get("benchmark_drawdown_pct")
            for row in drawdown_rows
            if isinstance(row.get("benchmark_drawdown_pct"), (int, float))
        ]

        run_summary.update(
            {
                "total_return_pct": total_return_pct,
                "benchmark_return_pct": benchmark_return_pct,
                "alpha_vs_benchmark_pct": (
                    round(total_return_pct - benchmark_return_pct, 6)
                    if total_return_pct is not None and benchmark_return_pct is not None
                    else None
                ),
                "cagr_pct": cagr_pct,
                "sharpe_ratio": sharpe_ratio,
                "max_drawdown_pct": min(strategy_drawdowns) if strategy_drawdowns else None,
                "benchmark_max_drawdown_pct": min(benchmark_drawdowns) if benchmark_drawdowns else None,
                "trade_count": None,
                "win_rate_pct": None,
            }
        )

        return run_summary

    def _build_chart_window(
        self,
        chart_data_by_run_id: dict[str, dict[str, Any]],
        expected_run_count: int,
    ) -> dict[str, str | None]:
        run_windows: list[dict[str, str]] = []

        for run_id, chart_data in chart_data_by_run_id.items():
            equity_rows = chart_data.get("equity_curve") or []
            if not equity_rows:
                continue

            start_date = equity_rows[0].get("date")
            end_date = equity_rows[-1].get("date")
            if start_date and end_date:
                run_windows.append(
                    {
                        "run_id": run_id,
                        "start_date": str(start_date),
                        "end_date": str(end_date),
                    }
                )

        if len(run_windows) != expected_run_count or not run_windows:
            return {
                "chart_window_mode": FULL_PERIOD_CHART,
                "chart_overlap_start": None,
                "chart_overlap_end": None,
            }

        overlap_start = max(window["start_date"] for window in run_windows)
        overlap_end = min(window["end_date"] for window in run_windows)
        has_common_overlap = overlap_start <= overlap_end
        distinct_windows = {
            (window["start_date"], window["end_date"])
            for window in run_windows
        }

        if len(distinct_windows) > 1 and has_common_overlap:
            return {
                "chart_window_mode": COMMON_OVERLAP_CHART,
                "chart_overlap_start": overlap_start,
                "chart_overlap_end": overlap_end,
            }

        return {
            "chart_window_mode": FULL_PERIOD_CHART,
            "chart_overlap_start": overlap_start if has_common_overlap else None,
            "chart_overlap_end": overlap_end if has_common_overlap else None,
        }

    def build_comparison(self, runs: list[Any]) -> dict[str, Any]:
        chart_data_by_run_id = self._load_chart_data_by_run_id(runs)
        metadata = self._build_window_metadata(runs, chart_data_by_run_id)

        if (
            metadata["window_mode"] == COMMON_OVERLAP_METRICS
            and metadata["overlap_start"] is not None
            and metadata["overlap_end"] is not None
        ):
            run_summaries = [
                self._build_overlap_run_summary(
                    run,
                    chart_data_by_run_id.get(str(run.id)),
                    metadata["overlap_start"],
                    metadata["overlap_end"],
                )
                for run in runs
            ]
        else:
            run_summaries = [self._build_full_period_run_summary(run) for run in runs]

        return {
            "runs": run_summaries,
            "metadata": metadata,
        }

    def build_equity_curves(self, runs: list[Any]) -> dict:
        strategy_curves = []
        benchmark_curves = []
        strategy_drawdown_curves = []
        benchmark_drawdown_curves = []
        chart_data_by_run_id = self._load_chart_data_by_run_id(runs)

        chart_window = self._build_chart_window(chart_data_by_run_id, len(runs))
        use_common_overlap = chart_window["chart_window_mode"] == COMMON_OVERLAP_CHART
        chart_overlap_start = chart_window["chart_overlap_start"]
        chart_overlap_end = chart_window["chart_overlap_end"]

        for run in runs:
            chart_data = chart_data_by_run_id.get(str(run.id))
            if chart_data is None:
                continue

            label = None
            benchmark_label = self._extract_benchmark_label(run, chart_data)
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

            if use_common_overlap:
                equity_rows = [
                    row
                    for row in equity_rows
                    if chart_overlap_start <= str(row.get("date")) <= chart_overlap_end
                ]
                drawdown_rows = [
                    row
                    for row in drawdown_rows
                    if chart_overlap_start <= str(row.get("date")) <= chart_overlap_end
                ]

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
                    "label": f"{benchmark_label} · {label}" if benchmark_label else label,
                    "benchmark_label": benchmark_label,
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
                    "label": f"{benchmark_label} · {label}" if benchmark_label else label,
                    "benchmark_label": benchmark_label,
                    "points": benchmark_drawdown_points,
                }
            )

        return {
            "strategy_curves": strategy_curves,
            "benchmark_curves": benchmark_curves,
            "strategy_drawdown_curves": strategy_drawdown_curves,
            "benchmark_drawdown_curves": benchmark_drawdown_curves,
            "chart_window_mode": chart_window["chart_window_mode"],
            "chart_overlap_start": chart_window["chart_overlap_start"],
            "chart_overlap_end": chart_window["chart_overlap_end"],
        }
