from __future__ import annotations

import re
from typing import Any

from market_simulator.services.draft_validation import validate_draft_config


_TICKER_PATTERN = re.compile(r"\b[A-Z]{2,6}\b")


def _extract_requested_symbols_from_prompt(prompt: str) -> set[str]:
    matches = set(_TICKER_PATTERN.findall(prompt))

    ignore_tokens = {
        "RSI",
        "SMA",
        "EMA",
        "MACD",
        "KD",
        "STOCHASTIC",
        "MONTH",
        "MONTHS",
        "VS",
        "VERSUS",
        "RETURN",
        "ANY",
        "ALL",
        "THEN",
        "WITHIN",
        "SEQUENCE",
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
    from market_simulator.settings import get_settings

    settings = get_settings()
    supported_symbols = set(settings.supported_etf_symbols)

    requested_symbols = _extract_requested_symbols_from_prompt(prompt)
    unsupported_requested = sorted(
        symbol for symbol in requested_symbols if symbol not in supported_symbols
    )
    if unsupported_requested:
        joined = ", ".join(unsupported_requested)
        raise ValueError(
            f"{joined} {'is' if len(unsupported_requested) == 1 else 'are'} not supported yet. "
            "This platform is currently ETF-first, so please use supported ETF symbols."
        )

    validate_draft_config(
        config=config,
        max_backtest_years=max_backtest_years,
    )