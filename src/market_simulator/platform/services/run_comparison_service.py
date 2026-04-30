from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import stdev
from typing import Any

from market_simulator.platform.services.run_chart_service import RunChartService

FULL_PERIOD_METRICS = "FULL_PERIOD_METRICS"
COMMON_OVERLAP_METRICS = "COMMON_OVERLAP_METRICS"
FULL_PERIOD_CHART = "FULL_PERIOD"
COMMON_OVERLAP_CHART = "COMMON_OVERLAP"

BENCHMARK_SYMBOL_KEYS = ("benchmark_symbol", "benchmark_ticker", "benchmark")
BENCHMARK_NAME_KEYS = ("benchmark_name", "benchmark_label")


@dataclass(frozen=True)
class ComparableResultRef:
    result_type: str
    run_id: str | None = None
    sweep_run_id: str | None = None
    variant_id: str | None = None


class ComparableResult:
    def __init__(
        self,
        *,
        id: str,
        result_ref: str,
        result_type: str,
        label: str,
        source_run: Any,
        summary_json: dict[str, Any],
        request_payload: dict[str, Any],
        artifact_manifest_json: dict[str, str] | None,
        strategy: Any = None,
        strategy_version: Any = None,
    ):
        self.id = id
        self.result_ref = result_ref
        self.result_type = result_type
        self.label = label
        self.source_run = source_run
        self.strategy = strategy
        self.strategy_version = strategy_version
        self.strategy_id = getattr(source_run, "strategy_id", None)
        self.strategy_version_id = getattr(source_run, "strategy_version_id", None)
        self.status = getattr(source_run, "status", None)
        self.summary_json = summary_json
        self.request_payload = request_payload
        self.artifact_manifest_json = artifact_manifest_json


def parse_comparable_result_ref(value: str) -> ComparableResultRef:
    raw = value.strip()
    if raw.startswith("run:"):
        run_id = raw.removeprefix("run:").strip()
        if not run_id:
            raise ValueError("Run result reference is missing a run id.")
        return ComparableResultRef(result_type="RUN", run_id=run_id)

    if raw.startswith("sweep_variant:"):
        parts = raw.split(":", 2)
        if len(parts) != 3 or not parts[1].strip() or not parts[2].strip():
            raise ValueError("Sweep variant result reference must be sweep_variant:<sweep_run_id>:<variant_id>.")
        return ComparableResultRef(
            result_type="SWEEP_VARIANT",
            sweep_run_id=parts[1].strip(),
            variant_id=parts[2].strip(),
        )

    raise ValueError(f"Unsupported comparable result reference: {raw}")


def run_result_ref(run_id: Any) -> str:
    return f"run:{run_id}"


def sweep_variant_result_ref(sweep_run_id: Any, variant_id: Any) -> str:
    return f"sweep_variant:{sweep_run_id}:{variant_id}"


def _short_run_id(run_id: Any) -> str:
    return str(run_id).split("-")[0]


def _metric_value(source: dict[str, Any], key: str) -> Any:
    return source.get(key)


def _variant_artifact_manifest(variant: dict[str, Any]) -> dict[str, str] | None:
    artifact_dir = variant.get("artifact_dir")
    if not isinstance(artifact_dir, str) or not artifact_dir.strip():
        return None

    variant_dir = Path(artifact_dir)
    return {
        "summary": str(variant_dir / "summary.json"),
        "sleeve_summary": str(variant_dir / "sleeve_summary.json"),
        "yearly_report": str(variant_dir / "yearly_report.csv"),
        "trade_log": str(variant_dir / "trade_log.csv"),
        "timeline": str(variant_dir / "timeline.csv"),
        "events": str(variant_dir / "events.csv"),
        "monthly_returns": str(variant_dir / "monthly_returns.csv"),
        "report_bundle": str(variant_dir / "report_bundle.json"),
    }


def _format_parameter_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return str(value)


def _compact_parameter_name(path: str) -> str:
    compact_names = {
        "entry_rule.threshold": "entry",
        "exit_rule.threshold": "exit",
        "entry_rule.lookback": "entry lookback",
        "exit_rule.lookback": "exit lookback",
        "entry_rule.fast_window": "entry fast",
        "exit_rule.fast_window": "exit fast",
        "entry_rule.slow_window": "entry slow",
        "exit_rule.slow_window": "exit slow",
    }
    return compact_names.get(path, path.split(".")[-1].replace("_", " "))


def format_sweep_variant_parameter_summary(parameters: Any) -> str:
    if not isinstance(parameters, dict) or not parameters:
        return "variant"

    entries = list(parameters.items())
    if len(entries) > 2:
        return f"{len(entries)} parameter changes"

    return " / ".join(
        f"{_compact_parameter_name(str(path))} {_format_parameter_value(value)}"
        for path, value in entries
    )


def find_sweep_variant(run: Any, variant_id: str) -> dict[str, Any] | None:
    summary_json = run.summary_json or {}
    results = summary_json.get("results")
    if isinstance(results, list):
        for result in results:
            if isinstance(result, dict) and str(result.get("variant_id")) == str(variant_id):
                return result

    best_variant = summary_json.get("best_variant")
    if isinstance(best_variant, dict) and str(best_variant.get("variant_id")) == str(variant_id):
        return best_variant

    return None


def sweep_variant_rank(run: Any, variant_id: str) -> int | None:
    results = (run.summary_json or {}).get("results")
    if not isinstance(results, list):
        return None

    for index, result in enumerate(results, start=1):
        if isinstance(result, dict) and str(result.get("variant_id")) == str(variant_id):
            return index

    return None


def _run_label(run: Any) -> str:
    if getattr(run, "strategy", None) is not None and getattr(run.strategy, "name", None):
        label = run.strategy.name
        if getattr(run, "strategy_version", None) is not None:
            version_number = getattr(run.strategy_version, "version_number", None)
            if version_number is not None:
                return f"{label} · v{version_number}"
        return label

    request_payload = run.request_payload or {}
    draft_config = request_payload.get("draft_config") if isinstance(request_payload, dict) else None
    base_config = request_payload.get("base_config") if isinstance(request_payload, dict) else None
    for source in (draft_config, base_config):
        if isinstance(source, dict) and isinstance(source.get("name"), str) and source["name"].strip():
            return source["name"].strip()

    return f"Draft run · {_short_run_id(getattr(run, 'id', ''))}"


def sweep_variant_label(run: Any, variant: dict[str, Any], rank: int | None) -> str:
    rank_label = f"Rank #{rank}" if rank is not None else "Variant"
    parameter_label = format_sweep_variant_parameter_summary(variant.get("parameters"))
    return f"{_run_label(run)} · {rank_label} · {parameter_label}"


def build_run_comparable_result(run: Any) -> ComparableResult:
    result_ref = run_result_ref(run.id)
    return ComparableResult(
        id=str(run.id),
        result_ref=result_ref,
        result_type="RUN",
        label=_run_label(run),
        source_run=run,
        strategy=getattr(run, "strategy", None),
        strategy_version=getattr(run, "strategy_version", None),
        summary_json=run.summary_json or {},
        request_payload=run.request_payload or {},
        artifact_manifest_json=run.artifact_manifest_json,
    )


def build_sweep_variant_comparable_result(
    run: Any,
    *,
    variant_id: str,
    variant: dict[str, Any],
    rank: int | None = None,
) -> ComparableResult:
    resolved_rank = rank if rank is not None else sweep_variant_rank(run, variant_id)
    ranking_metric = (run.summary_json or {}).get("ranking_metric")
    result_ref = sweep_variant_result_ref(run.id, variant_id)
    summary_json = {
        "source": "sweep_variant",
        "variant_id": variant_id,
        "total_return_pct": _metric_value(variant, "total_return_pct"),
        "benchmark_return_pct": _metric_value(variant, "benchmark_return_pct"),
        "alpha_vs_benchmark_pct": _metric_value(variant, "alpha_vs_benchmark_pct"),
        "cagr_pct": _metric_value(variant, "cagr_pct"),
        "sharpe_ratio": _metric_value(variant, "sharpe_ratio"),
        "max_drawdown_pct": _metric_value(variant, "max_drawdown_pct"),
        "benchmark_max_drawdown_pct": _metric_value(variant, "benchmark_max_drawdown_pct"),
        "trade_count": _metric_value(variant, "trade_count"),
        "win_rate_pct": _metric_value(variant, "win_rate_pct"),
    }
    return ComparableResult(
        id=result_ref,
        result_ref=result_ref,
        result_type="SWEEP_VARIANT",
        label=sweep_variant_label(run, variant, resolved_rank),
        source_run=run,
        strategy=getattr(run, "strategy", None),
        strategy_version=getattr(run, "strategy_version", None),
        summary_json=summary_json,
        request_payload={
            "source": "sweep_variant",
            "source_sweep_run_id": str(run.id),
            "source_variant_id": variant_id,
            "source_variant_rank": resolved_rank,
            "source_ranking_metric": ranking_metric if isinstance(ranking_metric, str) else None,
            "draft_config": variant.get("config") if isinstance(variant.get("config"), dict) else None,
        },
        artifact_manifest_json=_variant_artifact_manifest(variant),
    )


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
            "result_ref": getattr(run, "result_ref", str(run.id)),
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
            "result_ref": getattr(run, "result_ref", str(run.id)),
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
            "result_ref": getattr(run, "result_ref", str(run.id)),
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
            "result_ref": getattr(run, "result_ref", str(run.id)),
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
        request_payload = run.request_payload or {}
        source_variant_rank = request_payload.get("source_variant_rank")

        return {
            "run_id": str(run.id),
            "result_ref": getattr(run, "result_ref", str(run.id)),
            "result_type": getattr(run, "result_type", "RUN"),
            "label": getattr(run, "label", None),
            "strategy_id": str(run.strategy_id) if run.strategy_id else None,
            "strategy_version_id": str(run.strategy_version_id) if run.strategy_version_id else None,
            "strategy_name": run.strategy.name if run.strategy else None,
            "strategy_version_number": (
                run.strategy_version.version_number if run.strategy_version else None
            ),
            "source": request_payload.get("source"),
            "source_sweep_run_id": request_payload.get("source_sweep_run_id"),
            "source_variant_id": request_payload.get("source_variant_id"),
            "source_variant_rank": source_variant_rank if isinstance(source_variant_rank, int) else None,
            "source_ranking_metric": request_payload.get("source_ranking_metric"),
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
                        "result_ref": run_id,
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

    def _benchmark_curve_identity(self, curve: dict[str, Any]) -> str:
        benchmark_label = self._clean_benchmark_value(curve.get("benchmark_label"))
        if benchmark_label is not None:
            return benchmark_label.upper()

        return str(curve.get("result_ref") or curve.get("run_id") or "Benchmark")

    def _curve_date_window(self, curve: dict[str, Any]) -> tuple[str | None, str | None]:
        points = curve.get("points")
        if not isinstance(points, list) or not points:
            return (None, None)

        first_date = points[0].get("date") if isinstance(points[0], dict) else None
        last_date = points[-1].get("date") if isinstance(points[-1], dict) else None
        return (
            str(first_date) if first_date is not None else None,
            str(last_date) if last_date is not None else None,
        )

    def _curve_points_signature(self, curve: dict[str, Any]) -> tuple[tuple[str, float], ...]:
        signature = []
        for point in curve.get("points") or []:
            if not isinstance(point, dict):
                continue
            value = point.get("value")
            if not isinstance(value, (int, float)):
                continue
            signature.append((str(point.get("date")), round(float(value), 8)))
        return tuple(signature)

    def _dedupe_benchmark_curves(self, curves: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen_by_identity_window: dict[tuple[str, str | None, str | None], int] = {}
        conflict_counts: dict[tuple[str, str | None, str | None], int] = {}

        for curve in curves:
            identity = self._benchmark_curve_identity(curve)
            start_date, end_date = self._curve_date_window(curve)
            key = (identity.upper(), start_date, end_date)
            clean_curve = {
                **curve,
                "label": f"Benchmark: {identity}" if curve.get("benchmark_label") else "Benchmark",
                "benchmark_label": identity if curve.get("benchmark_label") else None,
            }

            existing_index = seen_by_identity_window.get(key)
            if existing_index is None:
                seen_by_identity_window[key] = len(deduped)
                conflict_counts[key] = 1
                deduped.append(clean_curve)
                continue

            existing_curve = deduped[existing_index]
            if self._curve_points_signature(existing_curve) == self._curve_points_signature(clean_curve):
                continue

            conflict_counts[key] += 1
            if conflict_counts[key] == 2:
                deduped[existing_index] = {
                    **existing_curve,
                    "label": f"{clean_curve['label']} (1)",
                }

            deduped.append(
                {
                    **clean_curve,
                    "label": f"{clean_curve['label']} ({conflict_counts[key]})",
                }
            )

        return deduped

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
                label = getattr(run, "label", None) or str(run.id)

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
                    "result_ref": getattr(run, "result_ref", str(run.id)),
                    "label": label,
                    "points": strategy_points,
                }
            )
            benchmark_curves.append(
                {
                    "run_id": str(run.id),
                    "result_ref": getattr(run, "result_ref", str(run.id)),
                    "label": f"Benchmark: {benchmark_label}" if benchmark_label else "Benchmark",
                    "benchmark_label": benchmark_label,
                    "points": benchmark_points,
                }
            )
            strategy_drawdown_curves.append(
                {
                    "run_id": str(run.id),
                    "result_ref": getattr(run, "result_ref", str(run.id)),
                    "label": label,
                    "points": strategy_drawdown_points,
                }
            )
            benchmark_drawdown_curves.append(
                {
                    "run_id": str(run.id),
                    "result_ref": getattr(run, "result_ref", str(run.id)),
                    "label": f"Benchmark: {benchmark_label}" if benchmark_label else "Benchmark",
                    "benchmark_label": benchmark_label,
                    "points": benchmark_drawdown_points,
                }
            )

        return {
            "strategy_curves": strategy_curves,
            "benchmark_curves": self._dedupe_benchmark_curves(benchmark_curves),
            "strategy_drawdown_curves": strategy_drawdown_curves,
            "benchmark_drawdown_curves": self._dedupe_benchmark_curves(benchmark_drawdown_curves),
            "chart_window_mode": chart_window["chart_window_mode"],
            "chart_overlap_start": chart_window["chart_overlap_start"],
            "chart_overlap_end": chart_window["chart_overlap_end"],
        }
