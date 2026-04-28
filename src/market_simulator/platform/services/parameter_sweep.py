from __future__ import annotations

import csv
import hashlib
import itertools
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.service import SimulationService


DEFAULT_MAX_VARIANTS = 25
DEFAULT_RANKING_METRIC = "sharpe"

RANKING_ALIASES = {
    "sharpe": "sharpe_ratio",
    "sharpe_ratio": "sharpe_ratio",
    "total_return": "total_return_pct",
    "total_return_pct": "total_return_pct",
    "benchmark_return": "benchmark_return_pct",
    "benchmark_return_pct": "benchmark_return_pct",
    "alpha": "alpha_vs_benchmark_pct",
    "alpha_pct": "alpha_vs_benchmark_pct",
    "alpha_vs_benchmark_pct": "alpha_vs_benchmark_pct",
    "cagr": "cagr_pct",
    "cagr_pct": "cagr_pct",
    "max_drawdown": "max_drawdown_pct",
    "max_drawdown_pct": "max_drawdown_pct",
    "trade_count": "trade_count",
}

SUMMARY_METRICS = [
    "total_return_pct",
    "benchmark_return_pct",
    "alpha_vs_benchmark_pct",
    "cagr_pct",
    "sharpe_ratio",
    "max_drawdown_pct",
    "trade_count",
]


class ParameterSweepError(ValueError):
    """A user-facing parameter sweep validation error."""


def _format_validation_error(exc: ValidationError, prefix: str) -> str:
    first_error = exc.errors()[0]
    location = ".".join(str(part) for part in first_error.get("loc", []))
    message = first_error.get("msg", "Invalid strategy config")
    if location:
        return f"{prefix} because {location} was invalid: {message}."
    return f"{prefix}: {message}."


def _parse_part(part: str) -> tuple[str, int | None]:
    if "[" in part and part.endswith("]"):
        name, idx = part[:-1].split("[", 1)
        return name, int(idx)
    return part, None


def get_nested(config: dict[str, Any], path: str) -> Any:
    current: Any = config
    for part in path.split("."):
        key, idx = _parse_part(part)
        current = current[key]
        if idx is not None:
            current = current[idx]
    return current


def set_nested(config: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: Any = config

    for part in parts[:-1]:
        key, idx = _parse_part(part)
        current = current[key]
        if idx is not None:
            current = current[idx]

    last_key, last_idx = _parse_part(parts[-1])
    if last_idx is None:
        current[last_key] = value
    else:
        current[last_key][last_idx] = value


def _normalize_grid(payload: dict[str, Any]) -> dict[str, list[Any]]:
    grid = payload.get("grid", payload.get("search_space"))

    if grid is None and isinstance(payload.get("parameters"), list):
        grid = {}
        for item in payload["parameters"]:
            if not isinstance(item, dict):
                raise ParameterSweepError("Each parameter must be an object with path and values.")
            path = item.get("path")
            values = item.get("values")
            if not isinstance(path, str) or not path.strip():
                raise ParameterSweepError("Each parameter must include a non-empty path.")
            grid[path] = values

    if not isinstance(grid, dict) or not grid:
        raise ParameterSweepError("Parameter sweep requires a non-empty grid.")

    normalized: dict[str, list[Any]] = {}
    for path, values in grid.items():
        if not isinstance(path, str) or not path.strip():
            raise ParameterSweepError("Parameter grid paths must be non-empty strings.")
        if not isinstance(values, list) or len(values) == 0:
            raise ParameterSweepError(f"Parameter '{path}' must include at least one value.")
        normalized[path] = values

    return normalized


def normalize_ranking_metric(metric: str | None) -> str:
    key = (metric or DEFAULT_RANKING_METRIC).strip().lower()
    normalized = RANKING_ALIASES.get(key)
    if normalized is None:
        allowed = ", ".join(sorted(RANKING_ALIASES))
        raise ParameterSweepError(f"Unsupported ranking_metric '{metric}'. Allowed values: {allowed}.")
    return normalized


def variant_count(grid: dict[str, list[Any]]) -> int:
    count = 1
    for values in grid.values():
        count *= len(values)
    return count


def enforce_variant_limit(count: int, max_variants: int) -> None:
    if count > max_variants:
        raise ParameterSweepError(
            f"Parameter sweep is limited to {max_variants} variants for your plan."
        )


def _short_value(value: Any) -> str:
    if value is None:
        return "null"
    text = str(value).lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-") or "value"


def _path_label(path: str) -> str:
    parts = [part for part in re.split(r"[.\[\]]+", path) if part]
    return parts[-1] if parts else path


def make_variant_name(base_name: str, assignments: dict[str, Any], index: int) -> str:
    suffix = "__".join(
        f"{_path_label(path)}-{_short_value(value)}"
        for path, value in assignments.items()
    )
    if len(suffix) > 80:
        suffix = suffix[:80].rstrip("-_.")
    return f"{base_name}-sweep-{index:03d}-{suffix}"


def make_variant_id(assignments: dict[str, Any]) -> str:
    payload = json.dumps(assignments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def generate_variant_configs(
    base_config: dict[str, Any],
    grid: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    keys = list(grid.keys())
    variants: list[dict[str, Any]] = []
    base_name = str(base_config.get("name") or "strategy")

    for index, combo in enumerate(itertools.product(*(grid[key] for key in keys)), start=1):
        assignments = dict(zip(keys, combo))
        config = deepcopy(base_config)
        try:
            for path, value in assignments.items():
                set_nested(config, path, value)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ParameterSweepError(
                f"Parameter path '{path}' could not be applied to the base config."
            ) from exc
        config["name"] = make_variant_name(base_name, assignments, index)
        variants.append(
            {
                "variant_id": make_variant_id(assignments),
                "variant_name": config["name"],
                "parameters": assignments,
                "config": config,
            }
        )

    return variants


def build_sweep_request(
    payload: dict[str, Any],
    *,
    fallback_base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ParameterSweepError("Parameter sweep request payload must be an object.")

    base_config = payload.get("base_config") or fallback_base_config
    if not isinstance(base_config, dict):
        raise ParameterSweepError("Parameter sweep requires base_config or a saved strategy version.")

    try:
        StrategyV2.model_validate(base_config)
    except ValidationError as exc:
        raise ParameterSweepError(
            _format_validation_error(exc, "Base strategy config is invalid")
        ) from exc

    grid = _normalize_grid(payload)
    requested_max_variants = payload.get("max_variants", DEFAULT_MAX_VARIANTS)
    if not isinstance(requested_max_variants, int) or requested_max_variants < 1:
        raise ParameterSweepError("max_variants must be a positive integer.")
    max_variants = min(requested_max_variants, DEFAULT_MAX_VARIANTS)

    count = variant_count(grid)
    enforce_variant_limit(count, max_variants)

    ranking_metric = normalize_ranking_metric(payload.get("ranking_metric"))
    variants = generate_variant_configs(base_config, grid)

    invalid_variants: list[str] = []
    for variant in variants:
        try:
            StrategyV2.model_validate(variant["config"])
        except ValidationError as exc:
            invalid_variants.append(
                _format_validation_error(
                    exc,
                    f"Variant {variant['variant_name']} is invalid",
                )
            )

    if invalid_variants:
        raise ParameterSweepError(" ".join(invalid_variants))

    return {
        "base_config": deepcopy(base_config),
        "grid": grid,
        "ranking_metric": ranking_metric,
        "max_variants": max_variants,
        "variant_count": count,
        "variants": variants,
    }


def ranking_value(row: dict[str, Any], ranking_metric: str) -> float:
    value = row.get(ranking_metric)
    if isinstance(value, (int, float)):
        return float(value)
    return float("-inf")


def sort_sweep_results(rows: list[dict[str, Any]], ranking_metric: str) -> list[dict[str, Any]]:
    successful = [row for row in rows if row.get("status") == "SUCCEEDED"]
    failed = [row for row in rows if row.get("status") != "SUCCEEDED"]
    successful.sort(key=lambda row: ranking_value(row, ranking_metric), reverse=True)
    return successful + failed


def _public_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "Variant execution failed."
    return message.splitlines()[0][:500]


def _result_row(
    *,
    variant: dict[str, Any],
    status: str,
    summary: dict[str, Any] | None = None,
    artifact_dir: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "variant_id": variant["variant_id"],
        "variant_name": variant["variant_name"],
        "parameters": variant["parameters"],
        "config": variant["config"],
        "status": status,
        "error": error,
        "artifact_dir": artifact_dir,
    }
    summary = summary or {}
    for metric in SUMMARY_METRICS:
        row[metric] = summary.get(metric)
    return row


def write_sweep_artifacts(
    *,
    output_dir: str | Path,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "sweep_summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )

    fieldnames = [
        "rank",
        "variant_id",
        "variant_name",
        "status",
        "error",
        "total_return_pct",
        "benchmark_return_pct",
        "alpha_vs_benchmark_pct",
        "cagr_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "trade_count",
        "artifact_dir",
        "parameters",
    ]
    with (output_dir / "sweep_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(results, start=1):
            writer.writerow(
                {
                    **{key: row.get(key) for key in fieldnames},
                    "rank": index if row.get("status") == "SUCCEEDED" else None,
                    "parameters": json.dumps(row.get("parameters", {}), sort_keys=True),
                }
            )


class ParameterSweepService:
    def __init__(self, simulation_service: SimulationService | None = None):
        self.simulation_service = simulation_service or SimulationService()

    def run_sweep(
        self,
        payload: dict[str, Any],
        *,
        output_dir: str | Path,
        fallback_base_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = build_sweep_request(
            payload,
            fallback_base_config=fallback_base_config,
        )

        results: list[dict[str, Any]] = []
        variant_root = Path(output_dir) / "variants"
        variant_root.mkdir(parents=True, exist_ok=True)

        for index, variant in enumerate(request["variants"], start=1):
            variant_dir = variant_root / f"{index:03d}_{variant['variant_id']}"
            try:
                result = self.simulation_service.run_from_config(
                    variant["config"],
                    output_dir=variant_dir,
                )
                results.append(
                    _result_row(
                        variant=variant,
                        status="SUCCEEDED",
                        summary=result.summary,
                        artifact_dir=result.artifact_dir,
                    )
                )
            except Exception as exc:
                results.append(
                    _result_row(
                        variant=variant,
                        status="FAILED",
                        error=_public_error(exc),
                    )
                )

        ranked_results = sort_sweep_results(results, request["ranking_metric"])
        best_variant = next(
            (row for row in ranked_results if row.get("status") == "SUCCEEDED"),
            None,
        )
        summary = {
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": request["ranking_metric"],
            "variant_count": request["variant_count"],
            "succeeded_count": sum(1 for row in results if row.get("status") == "SUCCEEDED"),
            "failed_count": sum(1 for row in results if row.get("status") != "SUCCEEDED"),
            "best_variant": best_variant,
            "results": ranked_results,
        }
        if best_variant is not None:
            for metric in SUMMARY_METRICS:
                summary[metric] = best_variant.get(metric)

        write_sweep_artifacts(
            output_dir=output_dir,
            summary=summary,
            results=ranked_results,
        )

        return {
            "summary": summary,
            "results": ranked_results,
        }
