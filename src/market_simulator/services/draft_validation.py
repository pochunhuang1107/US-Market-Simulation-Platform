from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.settings import get_settings


def _parse_iso_date(value: Any, field_name: str) -> date:
    label = "start date" if field_name == "start_date" else "end date"
    if not isinstance(value, str):
        raise ValueError(f"The {label} must use ISO format like 2021-04-14.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"The {label} must use ISO format like 2021-04-14.") from exc


def validate_draft_config(
    *,
    config: dict[str, Any],
    max_backtest_years: int,
) -> None:
    if not isinstance(config, dict):
        raise ValueError("The generated draft config was invalid. Please try again.")

    try:
        StrategyV2.model_validate(config)
    except ValidationError as exc:
        first_error = exc.errors()[0]
        location = ".".join(str(part) for part in first_error.get("loc", []))
        message = first_error.get("msg", "Invalid strategy config")
        if location:
            raise ValueError(
                f"I could not build a valid strategy draft because {location} was invalid: {message}."
            ) from exc
        raise ValueError(
            f"I could not build a valid strategy draft: {message}."
        ) from exc

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
        joined = ", ".join(unsupported_symbols)
        raise ValueError(
            f"{joined} {'is' if len(unsupported_symbols) == 1 else 'are'} not supported yet. "
            "This platform is currently ETF-first, so please use supported ETF symbols."
        )

    start_date = _parse_iso_date(config.get("start_date"), "start_date")
    end_date = _parse_iso_date(config.get("end_date"), "end_date")

    if end_date < start_date:
        raise ValueError("The end date must be on or after the start date.")

    if start_date < settings.supported_data_start or end_date > settings.supported_data_end:
        raise ValueError(
            "That date range is outside supported ETF data coverage "
            f"({settings.supported_data_start.isoformat()} to {settings.supported_data_end.isoformat()})."
        )

    backtest_years = (end_date - start_date).days / 365.25
    if backtest_years > max_backtest_years:
        raise ValueError(
            f"That date range exceeds your current plan limit of {max_backtest_years} years. "
            "Please shorten the range and try again."
        )