from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.services.strategy_builder_parsers import (
    SUPPORTED_REFERENCE_SERIES_SYMBOLS,
)
from market_simulator.settings import get_settings


MINIMUM_TRADE_SELF_BLOCKING_WARNING = (
    "Minimum trade size may block entries because entry size is at or below the "
    "minimum trade threshold. Whole-share rounding can make trades smaller than the minimum."
)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def collect_draft_config_warnings(config: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    allocation = config.get("allocation") if isinstance(config, dict) else None
    position_management = (
        config.get("position_management") if isinstance(config, dict) else None
    )

    if not isinstance(allocation, dict) or not isinstance(position_management, dict):
        return warnings

    minimum_trade_pct = _as_number(
        position_management.get("minimum_trade_pct_of_equity")
    )
    if minimum_trade_pct is None:
        return warnings

    entry_candidates = [
        _as_number(allocation.get("entry_value")),
        _as_number(position_management.get("scale_in_fraction")),
    ]
    if any(
        entry_value is not None and entry_value <= minimum_trade_pct
        for entry_value in entry_candidates
    ):
        warnings.append(MINIMUM_TRADE_SELF_BLOCKING_WARNING)

    return warnings


def _parse_iso_date(value: Any, field_name: str) -> date:
    label = "start date" if field_name == "start_date" else "end date"
    if not isinstance(value, str):
        raise ValueError(f"The {label} must use ISO format like 2021-04-14.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"The {label} must use ISO format like 2021-04-14.") from exc


def _collect_rule_symbols(rule: Any) -> list[str]:
    symbols: list[str] = []

    if not isinstance(rule, dict):
        return symbols

    kind = rule.get("kind")

    if kind == "atomic":
        symbol = rule.get("symbol")
        reference_symbol = rule.get("reference_symbol")
        if isinstance(symbol, str):
            symbols.append(symbol.upper())
        if isinstance(reference_symbol, str):
            symbols.append(reference_symbol.upper())
        return symbols

    if kind == "not":
        return _collect_rule_symbols(rule.get("rule"))

    if kind == "group":
        for child_rule in rule.get("rules", []):
            symbols.extend(_collect_rule_symbols(child_rule))
        return symbols

    if kind == "window":
        return _collect_rule_symbols(rule.get("rule"))

    if kind == "sequence":
        for child_rule in rule.get("steps", []):
            symbols.extend(_collect_rule_symbols(child_rule))
        return symbols

    return symbols


def validate_draft_config(
    *,
    config: dict[str, Any],
    max_backtest_years: int,
) -> list[str]:
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
    symbols_to_check.extend(_collect_rule_symbols(entry_rule))

    exit_rule = config.get("exit_rule") or {}
    symbols_to_check.extend(_collect_rule_symbols(exit_rule))

    unsupported_symbols = sorted(
        {
            symbol
            for symbol in symbols_to_check
            if symbol not in supported_symbols
            and symbol not in SUPPORTED_REFERENCE_SERIES_SYMBOLS
        }
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

    return collect_draft_config_warnings(config)


def validate_backtest_window(
    *,
    config: dict[str, Any],
    max_backtest_years: int,
) -> None:
    start_date = _parse_iso_date(config.get("start_date"), "start_date")
    end_date = _parse_iso_date(config.get("end_date"), "end_date")

    if end_date < start_date:
        raise ValueError("The end date must be on or after the start date.")

    settings = get_settings()
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
