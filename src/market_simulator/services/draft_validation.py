from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.settings import get_settings


def _parse_iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a valid ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO date") from exc


def validate_draft_config(
    *,
    config: dict[str, Any],
    max_backtest_years: int,
) -> None:
    if not isinstance(config, dict):
        raise ValueError("draft_config must be an object")

    try:
        StrategyV2.model_validate(config)
    except ValidationError as exc:
        first_error = exc.errors()[0]
        location = ".".join(str(part) for part in first_error.get("loc", []))
        message = first_error.get("msg", "Invalid strategy config")
        if location:
            raise ValueError(f"Invalid strategy config at {location}: {message}") from exc
        raise ValueError(f"Invalid strategy config: {message}") from exc

    settings = get_settings()
    supported_symbols = set(settings.supported_etf_symbols)

    symbols_to_check: list[str] = []

    tradable_symbol = config.get("tradable_symbol")
    if isinstance(tradable_symbol, str):
        symbols_to_check.append(tradable_symbol.upper())

    benchmark_symbol = config.get("benchmark_symbol")
    if isinstance(benchmark_symbol, str):
        symbols_to_check.append(benchmark_symbol.upper())

    reference_symbols = config.get("reference_symbols") or []
    if isinstance(reference_symbols, list):
        for symbol in reference_symbols:
            if isinstance(symbol, str):
                symbols_to_check.append(symbol.upper())

    entry_rule = config.get("entry_rule") or {}
    if isinstance(entry_rule, dict):
        symbol = entry_rule.get("symbol")
        reference_symbol = entry_rule.get("reference_symbol")
        if isinstance(symbol, str):
            symbols_to_check.append(symbol.upper())
        if isinstance(reference_symbol, str):
            symbols_to_check.append(reference_symbol.upper())

    exit_rule = config.get("exit_rule") or {}
    if isinstance(exit_rule, dict):
        symbol = exit_rule.get("symbol")
        reference_symbol = exit_rule.get("reference_symbol")
        if isinstance(symbol, str):
            symbols_to_check.append(symbol.upper())
        if isinstance(reference_symbol, str):
            symbols_to_check.append(reference_symbol.upper())

    unsupported_symbols = sorted(
        {symbol for symbol in symbols_to_check if symbol not in supported_symbols}
    )
    if unsupported_symbols:
        raise ValueError(
            "Unsupported symbol(s) for current ETF coverage: "
            + ", ".join(unsupported_symbols)
        )

    start_date = _parse_iso_date(config.get("start_date"), "start_date")
    end_date = _parse_iso_date(config.get("end_date"), "end_date")

    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")

    if start_date < settings.supported_data_start or end_date > settings.supported_data_end:
        raise ValueError(
            "Requested backtest range is outside supported data coverage "
            f"({settings.supported_data_start.isoformat()} to {settings.supported_data_end.isoformat()})"
        )

    backtest_years = (end_date - start_date).days / 365.25
    if backtest_years > max_backtest_years:
        raise ValueError(
            f"Requested backtest window exceeds your plan limit of {max_backtest_years} years"
        )