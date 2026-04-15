from __future__ import annotations

import re
from datetime import date
from typing import Any

from market_simulator.settings import get_settings


_TICKER_PATTERN = re.compile(r"\b[A-Z]{2,6}\b")


def _parse_iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a valid ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO date") from exc


def _extract_requested_symbols_from_prompt(prompt: str) -> set[str]:
    matches = set(_TICKER_PATTERN.findall(prompt))

    ignore_tokens = {
        "RSI",
        "SMA",
        "EMA",
        "MACD",
        "AND",
        "OR",
        "NOT",
        "DAY",
        "DAYS",
        "BAR",
        "BARS",
    }

    return {token for token in matches if token not in ignore_tokens}


def validate_strategy_builder_request(
    *,
    prompt: str,
    config: dict[str, Any],
    max_backtest_years: int,
) -> None:
    settings = get_settings()
    supported_symbols = set(settings.supported_etf_symbols)

    requested_symbols = _extract_requested_symbols_from_prompt(prompt)
    unsupported_requested = sorted(
        symbol for symbol in requested_symbols if symbol not in supported_symbols
    )
    if unsupported_requested:
        raise ValueError(
            "Unsupported symbol(s) for current ETF coverage: "
            + ", ".join(unsupported_requested)
        )

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

    unsupported_config = sorted(
        {symbol for symbol in symbols_to_check if symbol not in supported_symbols}
    )
    if unsupported_config:
        raise ValueError(
            "Unsupported symbol(s) for current ETF coverage: "
            + ", ".join(unsupported_config)
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