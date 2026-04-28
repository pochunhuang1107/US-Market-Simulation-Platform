from __future__ import annotations

import re
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderAnswerType,
    StrategyBuilderGuidanceType,
    StrategyBuilderResponseType,
    StrategyBuilderValidationType,
)
from market_simulator.services.etf_metadata_service import get_etf_history_range
from market_simulator.services.strategy_builder_capabilities import (
    DEFAULT_GUIDANCE_ACTIONS,
    SUPPORTED_STRATEGY_TYPES_MESSAGE,
    UNSUPPORTED_EDIT_SUGGESTED_ACTION,
)
from market_simulator.settings import get_settings


_TICKER_PATTERN = re.compile(r"\b[A-Z]{2,6}\b")
_NON_SYMBOL_TOKENS = {
    "ETF",
    "ETFS",
    "RSI",
    "SMA",
    "EMA",
    "MACD",
    "KD",
}
_PREFERRED_EXAMPLE_SYMBOLS = ("QQQ", "SPY", "DIA", "IWM", "VTI")


def _supported_symbol_examples(symbols: list[str]) -> list[str]:
    preferred = [symbol for symbol in _PREFERRED_EXAMPLE_SYMBOLS if symbol in symbols]
    return preferred or symbols[:5]


def _format_symbol_examples(symbols: list[str]) -> str:
    return ", ".join(_supported_symbol_examples(symbols))


def _extract_prompt_symbols(prompt: str) -> list[str]:
    found: list[str] = []
    for candidate in _TICKER_PATTERN.findall(prompt):
        symbol = candidate.upper()
        if symbol in _NON_SYMBOL_TOKENS or symbol in found:
            continue
        found.append(symbol)
    return found


def _include_configured_symbols_from_prompt(
    *,
    prompt: str,
    prompt_symbols: list[str],
    supported_symbols: list[str],
) -> list[str]:
    found = list(prompt_symbols)
    for symbol in supported_symbols:
        if symbol in found:
            continue
        if re.search(rf"\b{re.escape(symbol)}\b", prompt, flags=re.IGNORECASE):
            found.append(symbol)
    return found


def _safe_get_etf_history_range(symbol: str):
    try:
        return get_etf_history_range(symbol)
    except (BotoCoreError, ClientError, ValueError):
        return None


def _build_supported_symbols_answer(symbols: list[str]) -> tuple[str, dict[str, Any]]:
    examples = _format_symbol_examples(symbols)
    return (
        f"Supported ETF symbols right now include {examples}. "
        f"The full configured ETF universe is: {', '.join(symbols)}.",
        {
            "answer_type": StrategyBuilderAnswerType.SUPPORTED_SYMBOLS,
            "supported_symbols": symbols,
            "supported_data_start": None,
            "supported_data_end": None,
            "max_backtest_years": None,
        },
    )


def _build_unsupported_symbol_answer(
    *,
    symbols: list[str],
    supported_symbols: list[str],
) -> tuple[str, dict[str, Any]]:
    joined = ", ".join(symbols)
    verb = "is" if len(symbols) == 1 else "are"
    examples = _format_symbol_examples(supported_symbols)
    return (
        f"{joined} {verb} not currently available. "
        "This platform currently supports ETF strategy research. "
        f"Try {examples}.",
        {
            "answer_type": StrategyBuilderAnswerType.SUPPORTED_SYMBOLS,
            "supported_symbols": supported_symbols,
            "supported_data_start": None,
            "supported_data_end": None,
            "max_backtest_years": None,
        },
    )


def _build_symbol_coverage_answer(
    *,
    symbol: str,
    max_backtest_years: int,
) -> tuple[str, dict[str, Any]]:
    history = _safe_get_etf_history_range(symbol)
    if history is None:
        return (
            f"I could not find coverage metadata for {symbol}, but supported ETF strategies "
            "will be validated before simulation.",
            {
                "answer_type": StrategyBuilderAnswerType.DATA_COVERAGE,
                "supported_symbols": [symbol],
                "supported_data_start": None,
                "supported_data_end": None,
                "max_backtest_years": max_backtest_years,
            },
        )

    return (
        f"{symbol} coverage is available from "
        f"{history.first_available_date.isoformat()} to {history.last_available_date.isoformat()}. "
        f"Your current plan allows up to {max_backtest_years} years per backtest.",
        {
            "answer_type": StrategyBuilderAnswerType.DATA_COVERAGE,
            "supported_symbols": [symbol],
            "supported_data_start": history.first_available_date.isoformat(),
            "supported_data_end": history.last_available_date.isoformat(),
            "max_backtest_years": max_backtest_years,
        },
    )


def _build_answer_message(
    *,
    prompt: str,
    max_backtest_years: int,
) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    prompt_lower = prompt.lower()
    symbols = sorted(settings.supported_etf_symbols)
    prompt_symbols = _include_configured_symbols_from_prompt(
        prompt=prompt,
        prompt_symbols=_extract_prompt_symbols(prompt),
        supported_symbols=symbols,
    )
    unsupported_symbols = [symbol for symbol in prompt_symbols if symbol not in symbols]

    if unsupported_symbols:
        return _build_unsupported_symbol_answer(
            symbols=unsupported_symbols,
            supported_symbols=symbols,
        )

    if "individual stock" in prompt_lower or "individual stocks" in prompt_lower or "stock" in prompt_lower:
        examples = _format_symbol_examples(symbols)
        return (
            "Individual stocks are not currently supported. "
            "This platform currently focuses on ETF strategy research. "
            f"Try {examples}.",
            {
                "answer_type": StrategyBuilderAnswerType.SUPPORTED_SYMBOLS,
                "supported_symbols": symbols,
                "supported_data_start": None,
                "supported_data_end": None,
                "max_backtest_years": None,
            },
        )

    if "date" in prompt_lower or "range" in prompt_lower or "history" in prompt_lower or "coverage" in prompt_lower:
        if prompt_symbols:
            return _build_symbol_coverage_answer(
                symbol=prompt_symbols[0],
                max_backtest_years=max_backtest_years,
            )

        return (
            "Supported data coverage is "
            f"{settings.supported_data_start.isoformat()} to {settings.supported_data_end.isoformat()}, "
            f"and your current plan allows up to {max_backtest_years} years per backtest.",
            {
                "answer_type": StrategyBuilderAnswerType.DATA_COVERAGE,
                "supported_symbols": [],
                "supported_data_start": settings.supported_data_start.isoformat(),
                "supported_data_end": settings.supported_data_end.isoformat(),
                "max_backtest_years": max_backtest_years,
            },
        )

    if "benchmark" in prompt_lower and prompt_symbols:
        symbol = prompt_symbols[0]
        return (
            f"Yes. {symbol} is in the supported ETF universe and can be used as a benchmark.",
            {
                "answer_type": StrategyBuilderAnswerType.SUPPORTED_SYMBOLS,
                "supported_symbols": symbols,
                "supported_data_start": None,
                "supported_data_end": None,
                "max_backtest_years": None,
            },
        )

    if "symbol" in prompt_lower or "symbols" in prompt_lower or "etf" in prompt_lower or "etfs" in prompt_lower:
        return _build_supported_symbols_answer(symbols)

    if "limit" in prompt_lower or "plan" in prompt_lower:
        return (
            "The builder applies plan guardrails such as max prompt length, daily prompt limits, "
            f"and a maximum backtest window of {max_backtest_years} years.",
            {
                "answer_type": StrategyBuilderAnswerType.PLAN_LIMITS,
                "supported_symbols": [],
                "supported_data_start": None,
                "supported_data_end": None,
                "max_backtest_years": max_backtest_years,
            },
        )

    if (
        "strategy type" in prompt_lower
        or "strategy types" in prompt_lower
        or "what strategies" in prompt_lower
        or "which strategies" in prompt_lower
        or "what can i build" in prompt_lower
        or "what can i ask" in prompt_lower
        or "what can you do" in prompt_lower
        or "indicator" in prompt_lower
        or "indicators" in prompt_lower
        or "rule type" in prompt_lower
        or "rule types" in prompt_lower
    ):
        return (
            SUPPORTED_STRATEGY_TYPES_MESSAGE,
            {
                "answer_type": StrategyBuilderAnswerType.SUPPORTED_STRATEGY_TYPES,
                "supported_symbols": [],
                "supported_data_start": None,
                "supported_data_end": None,
                "max_backtest_years": max_backtest_years,
            },
        )

    return (
        "I can help answer ETF coverage questions, create a new draft, update your current draft, "
        "or explain why a requested edit cannot be applied.",
        {
            "answer_type": StrategyBuilderAnswerType.GENERAL,
            "supported_symbols": [],
            "supported_data_start": None,
            "supported_data_end": None,
            "max_backtest_years": max_backtest_years,
        },
    )


def build_validation_data(
    *,
    message: str,
    max_backtest_years: int,
) -> dict[str, Any]:
    settings = get_settings()

    unsupported_match = re.findall(r"\b[A-Z]{2,6}\b", message)
    if "not supported yet" in message and "ETF-first" in message:
        inferred = sorted(
            {
                token
                for token in unsupported_match
                if token not in settings.supported_etf_symbols and token != "ETF"
            }
        )
        return {
            "validation_type": StrategyBuilderValidationType.UNSUPPORTED_SYMBOL,
            "unsupported_symbols": inferred,
            "supported_data_start": None,
            "supported_data_end": None,
            "max_backtest_years": None,
            "suggested_action": "Try a supported ETF symbol instead.",
        }

    if "outside supported ETF data coverage" in message:
        return {
            "validation_type": StrategyBuilderValidationType.DATA_COVERAGE,
            "unsupported_symbols": [],
            "supported_data_start": settings.supported_data_start.isoformat(),
            "supported_data_end": settings.supported_data_end.isoformat(),
            "max_backtest_years": None,
            "suggested_action": "Choose a date range inside the supported ETF data window.",
        }

    if "current plan limit" in message and "shorten the range" in message:
        return {
            "validation_type": StrategyBuilderValidationType.PLAN_LIMIT,
            "unsupported_symbols": [],
            "supported_data_start": None,
            "supported_data_end": None,
            "max_backtest_years": max_backtest_years,
            "suggested_action": "Shorten the date range and try again.",
        }

    if "must use ISO format like 2021-04-14" in message:
        return {
            "validation_type": StrategyBuilderValidationType.INVALID_DATE_FORMAT,
            "unsupported_symbols": [],
            "supported_data_start": None,
            "supported_data_end": None,
            "max_backtest_years": None,
            "suggested_action": "Use ISO format like 2021-04-14.",
        }

    if "edit type is not supported yet" in message:
        return {
            "validation_type": StrategyBuilderValidationType.UNSUPPORTED_EDIT,
            "unsupported_symbols": [],
            "supported_data_start": None,
            "supported_data_end": None,
            "max_backtest_years": None,
            "suggested_action": UNSUPPORTED_EDIT_SUGGESTED_ACTION,
        }

    return {
        "validation_type": StrategyBuilderValidationType.GENERAL,
        "unsupported_symbols": [],
        "supported_data_start": None,
        "supported_data_end": None,
        "max_backtest_years": None,
        "suggested_action": None,
    }


def _build_guidance_data(
    *,
    guidance_type: StrategyBuilderGuidanceType,
) -> dict[str, Any]:
    default_actions = list(DEFAULT_GUIDANCE_ACTIONS)

    if guidance_type == StrategyBuilderGuidanceType.UNSUPPORTED_EDIT_TARGET:
        return {
            "guidance_type": guidance_type,
            "suggested_actions": default_actions,
        }

    if guidance_type == StrategyBuilderGuidanceType.NO_CHANGE:
        return {
            "guidance_type": guidance_type,
            "suggested_actions": default_actions,
        }

    return {
        "guidance_type": StrategyBuilderGuidanceType.GENERAL_GUIDANCE,
        "suggested_actions": default_actions,
    }


def _build_response(
    *,
    response_type: StrategyBuilderResponseType,
    message: str,
    config: dict[str, Any] | None = None,
    summary: str | None = None,
    warnings: list[str] | None = None,
    assumptions: list[str] | None = None,
    changes: list[str] | None = None,
    answer_data: dict[str, Any] | None = None,
    validation_data: dict[str, Any] | None = None,
    guidance_data: dict[str, Any] | None = None,
    sweep_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "response_type": response_type,
        "message": message,
        "config": config,
        "summary": summary,
        "warnings": warnings or [],
        "assumptions": assumptions or [],
        "changes": changes or [],
        "answer_data": answer_data,
        "validation_data": validation_data,
        "guidance_data": guidance_data,
        "sweep_draft": sweep_draft,
    }


__all__ = [
    "_build_answer_message",
    "_build_guidance_data",
    "_build_response",
    "build_validation_data",
]
