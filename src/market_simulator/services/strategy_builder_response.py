from __future__ import annotations

import re
from typing import Any

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderAnswerType,
    StrategyBuilderGuidanceType,
    StrategyBuilderResponseType,
    StrategyBuilderValidationType,
)
from market_simulator.services.strategy_builder_capabilities import (
    DEFAULT_GUIDANCE_ACTIONS,
    SUPPORTED_STRATEGY_TYPES_MESSAGE,
    UNSUPPORTED_EDIT_SUGGESTED_ACTION,
)
from market_simulator.settings import get_settings

def _build_answer_message(
    *,
    prompt: str,
    max_backtest_years: int,
) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    prompt_lower = prompt.lower()

    if "symbol" in prompt_lower or "etf" in prompt_lower:
        symbols = sorted(settings.supported_etf_symbols)
        return (
            f"Supported ETF symbols right now are: {', '.join(symbols)}.",
            {
                "answer_type": StrategyBuilderAnswerType.SUPPORTED_SYMBOLS,
                "supported_symbols": symbols,
                "supported_data_start": None,
                "supported_data_end": None,
                "max_backtest_years": None,
            },
        )

    if "date" in prompt_lower or "range" in prompt_lower or "history" in prompt_lower:
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
    }


__all__ = [
    "_build_answer_message",
    "_build_guidance_data",
    "_build_response",
    "build_validation_data",
]