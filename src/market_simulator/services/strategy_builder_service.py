from __future__ import annotations

import re
from datetime import date

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderAnswerType,
    StrategyBuilderGenerateRequest,
    StrategyBuilderGuidanceType,
    StrategyBuilderResponseType,
    StrategyBuilderValidationType,
)
from market_simulator.models.strategy_v2 import StrategyV2
from datetime import timedelta
from market_simulator.services.etf_metadata_service import get_etf_history_range
from market_simulator.services.strategy_builder_capabilities import (
    DEFAULT_GUIDANCE_ACTIONS,
    NO_CHANGE_MESSAGE,
    SUPPORTED_STRATEGY_TYPES_MESSAGE,
    UNSUPPORTED_EDIT_MESSAGE,
    UNSUPPORTED_EDIT_SUGGESTED_ACTION,
)
from market_simulator.settings import get_settings

from typing import Any


SUPPORTED_SYMBOLS = frozenset(get_settings().supported_etf_symbols)


def _build_fallback_default_date_range(*, max_backtest_years: int) -> tuple[str, str]:
    settings = get_settings()
    end_date = settings.supported_data_end
    approx_days = int(max_backtest_years * 365.25)
    candidate_start = end_date - timedelta(days=approx_days)
    start_date = max(settings.supported_data_start, candidate_start)
    return start_date.isoformat(), end_date.isoformat()


def _build_default_date_range(
    *,
    symbol: str,
    max_backtest_years: int,
) -> tuple[str, str, list[str]]:
    settings = get_settings()
    assumptions: list[str] = []

    history = get_etf_history_range(symbol)
    if history is None:
        start_date, end_date = _build_fallback_default_date_range(
            max_backtest_years=max_backtest_years
        )
        assumptions.append(
            f"No ETF metadata was found for {symbol}, so the default platform backtest range was used."
        )
        return start_date, end_date, assumptions

    effective_end = min(settings.supported_data_end, history.last_available_date)
    approx_days = int(max_backtest_years * 365.25)
    candidate_start = effective_end - timedelta(days=approx_days)
    effective_start = max(
        settings.supported_data_start,
        history.first_available_date,
        candidate_start,
    )

    if effective_start == history.first_available_date:
        assumptions.append(
            f"Used available history for {symbol} starting on {history.first_available_date.isoformat()}."
        )

    if effective_end == history.last_available_date and history.last_available_date < settings.supported_data_end:
        assumptions.append(
            f"Used available history for {symbol} ending on {history.last_available_date.isoformat()}."
        )

    return effective_start.isoformat(), effective_end.isoformat(), assumptions


def _extract_symbols(text: str) -> list[str]:
    found: list[str] = []
    for candidate in re.findall(r"\b[A-Z]{2,5}\b", text):
        symbol = candidate.upper()
        if symbol in SUPPORTED_SYMBOLS and symbol not in found:
            found.append(symbol)
    return found


def _extract_primary_symbol(text: str) -> tuple[str, list[str]]:
    assumptions: list[str] = []
    symbols = _extract_symbols(text)
    if symbols:
        return symbols[0], assumptions
    assumptions.append("Used QQQ as the tradable symbol by default.")
    return "QQQ", assumptions


def _extract_tradable_symbol_edit(text: str) -> str | None:
    patterns = [
        r"change\s+(?:this\s+strategy|strategy|tradable\s+symbol)\s+to\s+([A-Z]{2,5})",
        r"set\s+tradable\s+symbol\s+to\s+([A-Z]{2,5})",
        r"use\s+([A-Z]{2,5})\s+as\s+(?:the\s+)?tradable\s+symbol",
        r"switch\s+(?:this\s+strategy\s+)?to\s+([A-Z]{2,5})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).upper()
            if candidate in SUPPORTED_SYMBOLS:
                return candidate
    return None


def _has_benchmark_edit_intent(text: str) -> bool:
    return bool(
        re.search(
            r"\bbenchmark\b|\bas benchmark\b|set benchmark|benchmark is|change benchmark",
            text,
            flags=re.IGNORECASE,
        )
    )


def _rewrite_rule_tradable_symbol(
    rule: dict,
    *,
    new_symbol: str,
) -> dict:
    if not isinstance(rule, dict):
        return rule

    kind = rule.get("kind")
    updated_rule = dict(rule)

    if kind == "atomic":
        if updated_rule.get("type") != "month_in":
            updated_rule["symbol"] = new_symbol
        return updated_rule

    if kind == "not":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _rewrite_rule_tradable_symbol(
                nested_rule,
                new_symbol=new_symbol,
            )
        return updated_rule

    if kind == "group":
        updated_rule["rules"] = [
            _rewrite_rule_tradable_symbol(child_rule, new_symbol=new_symbol)
            if isinstance(child_rule, dict)
            else child_rule
            for child_rule in updated_rule.get("rules", [])
        ]
        return updated_rule

    if kind == "window":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _rewrite_rule_tradable_symbol(
                nested_rule,
                new_symbol=new_symbol,
            )
        return updated_rule

    if kind == "sequence":
        updated_rule["steps"] = [
            _rewrite_rule_tradable_symbol(step, new_symbol=new_symbol)
            if isinstance(step, dict)
            else step
            for step in updated_rule.get("steps", [])
        ]
        return updated_rule

    return updated_rule


def _extract_benchmark_symbol(text: str, default_symbol: str) -> tuple[str, list[str]]:
    assumptions: list[str] = []

    patterns = [
        r"benchmark(?:\s+(?:to|as|=|is))?\s+([A-Z]{2,5})",
        r"use\s+([A-Z]{2,5})\s+as\s+benchmark",
        r"using\s+([A-Z]{2,5})\s+as\s+benchmark",
        r"with\s+([A-Z]{2,5})\s+as\s+benchmark",
        r"set\s+benchmark\s+to\s+([A-Z]{2,5})",
        r"change\s+benchmark\s+to\s+([A-Z]{2,5})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).upper()
            if candidate in SUPPORTED_SYMBOLS:
                return candidate, assumptions

    assumptions.append("Used the tradable symbol as the benchmark by default.")
    return default_symbol, assumptions


def _extract_reference_symbols(
    text: str,
    tradable_symbol: str,
    benchmark_symbol: str,
) -> list[str]:
    symbols = _extract_symbols(text)
    return [s for s in symbols if s not in {tradable_symbol, benchmark_symbol}]


def _extract_date_range(
    text: str,
    *,
    symbol: str,
    max_backtest_years: int,
) -> tuple[date, date, list[str]]:
    assumptions: list[str] = []

    dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if len(dates) >= 2:
        return date.fromisoformat(dates[0]), date.fromisoformat(dates[1]), assumptions

    range_match = re.search(
        r"from\s+(20\d{2})\s+to\s+(20\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if range_match:
        start_year = int(range_match.group(1))
        end_year = int(range_match.group(2))
        return date(start_year, 1, 1), date(end_year, 12, 31), assumptions

    default_start_date, default_end_date, history_assumptions = _build_default_date_range(
        symbol=symbol,
        max_backtest_years=max_backtest_years,
    )
    assumptions.extend(history_assumptions)
    assumptions.append(
        f"Used the default backtest range {default_start_date} to {default_end_date}."
    )
    return (
        date.fromisoformat(default_start_date),
        date.fromisoformat(default_end_date),
        assumptions,
    )


def _has_current_config(req: StrategyBuilderGenerateRequest) -> bool:
    current_config = req.context.current_config if req.context else None
    return isinstance(current_config, dict) and bool(current_config)


def _extract_explicit_date_edits(text: str) -> dict[str, str]:
    updates: dict[str, str] = {}

    start_patterns = [
        r"change\s+start\s+date\s+to\s+(20\d{2}-\d{2}-\d{2})",
        r"set\s+start\s+date\s+to\s+(20\d{2}-\d{2}-\d{2})",
        r"start\s+date\s+(?:to|as)\s+(20\d{2}-\d{2}-\d{2})",
    ]
    end_patterns = [
        r"change\s+end\s+date\s+to\s+(20\d{2}-\d{2}-\d{2})",
        r"set\s+end\s+date\s+to\s+(20\d{2}-\d{2}-\d{2})",
        r"end\s+date\s+(?:to|as)\s+(20\d{2}-\d{2}-\d{2})",
    ]

    for pattern in start_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            updates["start_date"] = match.group(1)
            break

    for pattern in end_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            updates["end_date"] = match.group(1)
            break

    return updates


def _has_date_edit_intent(text: str) -> bool:
    return bool(
        re.search(
            r"(?:change|set|update).*(?:start\s+date|end\s+date)|"
            r"(?:start\s+date|end\s+date).*(?:change|set|update)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_edit_request(text: str) -> bool:
    return bool(
        re.search(
            r"\b(change|set|update|add|remove|delete|use|replace|switch|make)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_supported_edit_request(text: str) -> bool:
    supported_patterns = [
        r"\b(start\s+date|end\s+date)\b",
        r"\btradable\s+symbol\b",
        r"\bbenchmark\b",
        r"\bstop\s+loss\b",
        r"\btake\s+profit\b",
        r"\ballocation\b",
        r"\bcooldown\b",
        r"\brsi\b",
        r"\bmean\s+reversion\b",
        r"\bmoving\s+average\b",
        r"\bsma\b",
        r"\bmacd\b",
        r"\bkd\b",
        r"\bstochastic\b",
        r"\bseasonality\b",
        r"\bmonth\b",
        r"\bmonths\b",
        r"\brelative\s+strength\b",
        r"\brelative\s+return\b",
        r"\boutperform\b",
        r"\bwithin\s+\d+\s+bars?\b",
        r"\bthen\b",
        r"\bsequence\b",
        r"\b(entry|exit)\s+window\b",
        r"\bwindow\s+mode\b",
        r"\b(entry|exit)\s+sequence\b",
        r"\b(first|second)\s+step\s+of\s+(entry|exit)\s+sequence\b",
        r"\b(entry|exit)\s+group\s+operator\b",
        r"\b(first|second)\s+condition\s+of\s+(entry|exit)\s+group\b",
        r"\b(entry|exit)\s+window\s+inner\s+rule\b",
        r"\b(remove|delete)\s+(first|second)\s+condition\s+of\s+(entry|exit)\s+group\b",
        r"\b(remove|delete)\s+(entry|exit)\s+window\s+wrapper\b",
        r"\b(remove|delete)\s+(first|second)\s+step\s+of\s+(entry|exit)\s+sequence\b",
        r"\bpartial\s+take\s+profit\b",
        r"\bscale\s+in\b",
        r"\bscale\s+out\b",
        r"\bprofit\s+reduce\s+threshold\b",
        r"\bposition\s+management\b",
        r"\bcore\s+allocation\b",
        r"\bcore\s+overlay\b",
        r"\bcapital\b",
        r"\b(entry|exit)\s+(?:rule\s+)?(fast|slow)\s+window\b",
        r"\b(entry|exit)\s+rule\b",
        r"\bfast\s+window\b",
        r"\bslow\s+window\b",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in supported_patterns)


def _looks_like_question(prompt: str) -> bool:
    text = prompt.strip().lower()

    action_prefixes = (
        "create ",
        "build ",
        "generate ",
        "make ",
        "draft ",
        "update ",
        "change ",
        "set ",
        "remove ",
        "delete ",
    )
    if text.startswith(action_prefixes):
        return False

    action_patterns = [
        r"\bcreate\b.*\bstrategy\b",
        r"\bbuild\b.*\bstrategy\b",
        r"\bgenerate\b.*\bstrategy\b",
        r"\bchange\b.*\b(start date|end date|benchmark|stop loss|take profit|allocation|rsi)\b",
        r"\bset\b.*\b(start date|end date|benchmark|stop loss|take profit|allocation|rsi)\b",
        r"\bupdate\b.*\b(start date|end date|benchmark|stop loss|take profit|allocation|rsi)\b",
        r"\bremove\b.*\b(stop loss|take profit|cooldown)\b",
    ]
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in action_patterns):
        return False

    if prompt.strip().endswith("?"):
        return True

    return text.startswith(
        (
            "what ",
            "which ",
            "how ",
            "can i ",
            "do you ",
            "is ",
            "are ",
            "why ",
            "when ",
            "show me ",
            "tell me ",
            "list ",
        )
    )


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
        unsupported_symbols = [
            token
            for token in unsupported_match
            if token in {"SPY", "QQQ", "IWM", "DIA", "VTI"} or token not in settings.supported_etf_symbols
        ]
        inferred = [
            token for token in unsupported_symbols if token not in settings.supported_etf_symbols
        ]
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


def _extract_initial_capital(text: str) -> tuple[float, list[str]]:
    assumptions: list[str] = []

    patterns = [
        r"(?:initial\s+capital|capital|starting\s+with|start\s+with)\s*\$?([\d,]+(?:\.\d+)?)",
        r"\$([\d,]+(?:\.\d+)?)\s+(?:initial\s+capital|capital)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "")), assumptions

    assumptions.append("Used default initial capital of 100000.")
    return 100000.0, assumptions


def _extract_allocation_value(text: str) -> tuple[float, list[str]]:
    assumptions: list[str] = []

    explicit_value = _extract_allocation_value_edit(text)
    if explicit_value is not None:
        return explicit_value, assumptions

    if re.search(
        r"all\s+capital|full\s+allocation|100%\s+of\s+equity",
        text,
        flags=re.IGNORECASE,
    ):
        return 1.0, assumptions

    assumptions.append("Used 100% of equity for position sizing by default.")
    return 1.0, assumptions


def _extract_percent(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1)) / 100.0
    return None


def _extract_int(text: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_rsi_rule(
    text: str,
    direction: str,
) -> tuple[int, float] | None:
    comparator_words = {
        "below": r"(?:below|under|<)",
        "above": r"(?:above|over|>)",
    }
    comparator = comparator_words[direction]

    patterns = [
        rf"rsi(?:\s*\(?(\d+)\)?)?[^.\n]*?{comparator}\s*(\d+(?:\.\d+)?)",
        rf"(?:buy|entry|sell|exit)[^.\n]*rsi[^.\n]*?{comparator}\s*(\d+(?:\.\d+)?)",
    ]

    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        groups = match.groups()
        if index == 0:
            lookback = int(groups[0]) if groups[0] else 14
            threshold = float(groups[1])
        else:
            lookback = 14
            threshold = float(groups[0])

        return lookback, threshold

    return None


def _extract_rsi_entry_threshold_edit(text: str) -> float | None:
    patterns = [
        r"change\s+rsi\s+entry\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+rsi\s+entry\s+to\s+(\d+(?:\.\d+)?)",
        r"rsi\s+entry\s+to\s+(\d+(?:\.\d+)?)",
        r"entry\s+rsi\s+to\s+(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_rsi_exit_threshold_edit(text: str) -> float | None:
    patterns = [
        r"change\s+rsi\s+exit\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+rsi\s+exit\s+to\s+(\d+(?:\.\d+)?)",
        r"rsi\s+exit\s+to\s+(\d+(?:\.\d+)?)",
        r"exit\s+rsi\s+to\s+(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_sma_crossover_pair(text: str) -> tuple[int, int] | None:
    patterns = [
        r"(\d+)\s*(?:day|d)?\s*sma\s*(?:cross(?:es)?|crossing)?\s*above\s*(\d+)\s*(?:day|d)?\s*sma",
        r"(\d+)\s*/\s*(\d+)\s*sma",
        r"(\d+)\s*(?:day|d)?\s+(?:and|\/)\s*(\d+)\s*(?:day|d)?\s+sma",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            fast_window = int(match.group(1))
            slow_window = int(match.group(2))
            if fast_window != slow_window:
                return fast_window, slow_window
    return None


def _extract_entry_fast_window_edit(text: str) -> int | None:
    patterns = [
        r"change\s+entry(?:\s+rule)?(?:\s+sma)?\s+fast\s+window\s+to\s+(\d+)",
        r"set\s+entry(?:\s+rule)?(?:\s+sma)?\s+fast\s+window\s+to\s+(\d+)",
        r"entry(?:\s+rule)?(?:\s+sma)?\s+fast\s+window\s+to\s+(\d+)",
    ]
    return _extract_int(text, patterns)


def _extract_entry_slow_window_edit(text: str) -> int | None:
    patterns = [
        r"change\s+entry(?:\s+rule)?(?:\s+sma)?\s+slow\s+window\s+to\s+(\d+)",
        r"set\s+entry(?:\s+rule)?(?:\s+sma)?\s+slow\s+window\s+to\s+(\d+)",
        r"entry(?:\s+rule)?(?:\s+sma)?\s+slow\s+window\s+to\s+(\d+)",
    ]
    return _extract_int(text, patterns)


def _extract_exit_fast_window_edit(text: str) -> int | None:
    patterns = [
        r"change\s+exit(?:\s+rule)?(?:\s+sma)?\s+fast\s+window\s+to\s+(\d+)",
        r"set\s+exit(?:\s+rule)?(?:\s+sma)?\s+fast\s+window\s+to\s+(\d+)",
        r"exit(?:\s+rule)?(?:\s+sma)?\s+fast\s+window\s+to\s+(\d+)",
    ]
    return _extract_int(text, patterns)


def _extract_exit_slow_window_edit(text: str) -> int | None:
    patterns = [
        r"change\s+exit(?:\s+rule)?(?:\s+sma)?\s+slow\s+window\s+to\s+(\d+)",
        r"set\s+exit(?:\s+rule)?(?:\s+sma)?\s+slow\s+window\s+to\s+(\d+)",
        r"exit(?:\s+rule)?(?:\s+sma)?\s+slow\s+window\s+to\s+(\d+)",
    ]
    return _extract_int(text, patterns)


_MONTH_NAME_TO_NUMBER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _extract_month_values(text: str) -> list[int] | None:
    found: list[int] = []

    for month_name, month_number in _MONTH_NAME_TO_NUMBER.items():
        if re.search(rf"\b{month_name}\b", text, flags=re.IGNORECASE):
            if month_number not in found:
                found.append(month_number)

    if not found:
        return None

    return sorted(found)


def _extract_relative_strength_rules(
    text: str,
    *,
    tradable_symbol: str,
    fallback_reference_symbol: str,
) -> tuple[dict, dict, list[str]] | None:
    text_lower = text.lower()
    if not any(
        phrase in text_lower
        for phrase in ("relative strength", "relative return", "outperform")
    ):
        return None

    assumptions: list[str] = []

    reference_symbol = None
    reference_match = re.search(
        r"(?:vs|versus|against|compared to|relative to)\s+([A-Z]{2,5})",
        text,
        flags=re.IGNORECASE,
    )
    if reference_match:
        candidate = reference_match.group(1).upper()
        if candidate in SUPPORTED_SYMBOLS and candidate != tradable_symbol:
            reference_symbol = candidate

    if reference_symbol is None:
        symbols = _extract_symbols(text)
        for symbol in symbols:
            if symbol != tradable_symbol:
                reference_symbol = symbol
                break

    if reference_symbol is None:
        if fallback_reference_symbol != tradable_symbol:
            reference_symbol = fallback_reference_symbol
            assumptions.append(
                f"Used {reference_symbol} as the reference symbol by default."
            )
        else:
            reference_symbol = "SPY" if tradable_symbol != "SPY" else "QQQ"
            assumptions.append(
                f"Used {reference_symbol} as the reference symbol by default."
            )

    lookback = _extract_int(
        text,
        [
            r"over\s+(\d+)\s+days?",
            r"lookback\s+(\d+)",
            r"(\d+)[-\s]?day",
        ],
    )
    if lookback is None:
        lookback = 20
        assumptions.append("Used 20-day lookback for relative strength by default.")

    threshold = _extract_percent(
        text,
        [
            r"with\s+(\d+(?:\.\d+)?)%\s+threshold",
            r"above\s+(\d+(?:\.\d+)?)%",
            r"by\s+(\d+(?:\.\d+)?)%",
        ],
    )
    if threshold is None:
        threshold = 0.03
        assumptions.append("Used 3.0% threshold for relative strength by default.")

    base_rule = {
        "kind": "atomic",
        "type": "relative_return_above",
        "symbol": tradable_symbol,
        "reference_symbol": reference_symbol,
        "lookback": lookback,
        "threshold": threshold,
    }

    entry_rule = dict(base_rule)
    exit_rule = {
        "kind": "not",
        "rule": dict(base_rule),
    }

    assumptions.append(
        "Interpreted relative strength language as entering when the tradable symbol outperforms the reference symbol over the selected lookback window."
    )

    return entry_rule, exit_rule, assumptions


def _extract_relative_strength_reference_symbol_edit(text: str) -> str | None:
    patterns = [
        r"change\s+relative\s+(?:strength|return)\s+reference(?:\s+symbol)?\s+to\s+([A-Z]{2,5})",
        r"set\s+relative\s+(?:strength|return)\s+reference(?:\s+symbol)?\s+to\s+([A-Z]{2,5})",
        r"change\s+relative\s+(?:strength|return)\s+(?:vs|versus|against|relative to)\s+([A-Z]{2,5})",
        r"set\s+relative\s+(?:strength|return)\s+(?:vs|versus|against|relative to)\s+([A-Z]{2,5})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _extract_relative_strength_lookback_edit(text: str) -> int | None:
    patterns = [
        r"change\s+relative\s+(?:strength|return)\s+lookback\s+to\s+(\d+)",
        r"set\s+relative\s+(?:strength|return)\s+lookback\s+to\s+(\d+)",
        r"change\s+relative\s+(?:strength|return)\s+to\s+\d+\s+days?",
        r"set\s+relative\s+(?:strength|return)\s+to\s+\d+\s+days?",
        r"relative\s+(?:strength|return)\s+over\s+(\d+)\s+days?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and match.groups():
            return int(match.group(1))
    return None


def _extract_relative_strength_threshold_edit(text: str) -> float | None:
    return _extract_percent(
        text,
        [
            r"change\s+relative\s+(?:strength|return)\s+threshold\s+to\s+(\d+(?:\.\d+)?)%",
            r"set\s+relative\s+(?:strength|return)\s+threshold\s+to\s+(\d+(?:\.\d+)?)%",
            r"relative\s+(?:strength|return)\s+threshold\s+to\s+(\d+(?:\.\d+)?)%",
        ],
    )


def _extract_entry_exit_rule_clauses(text: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"(?:entry|buy)\s+when\s+(.+?)(?:,\s*|\s+)(?:and\s+)?(?:exit|sell)\s+when\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None

    entry_clause = match.group(1).strip(" .,")
    exit_clause = match.group(2).strip(" .,")
    return entry_clause, exit_clause


def _split_clause_conditions(text: str) -> tuple[str | None, list[str]] | None:
    has_and = bool(re.search(r"\band\b", text, flags=re.IGNORECASE))
    has_or = bool(re.search(r"\bor\b", text, flags=re.IGNORECASE))

    if has_and and has_or:
        return None

    if has_and:
        operator = "AND"
        parts = re.split(r"\band\b", text, flags=re.IGNORECASE)
    elif has_or:
        operator = "OR"
        parts = re.split(r"\bor\b", text, flags=re.IGNORECASE)
    else:
        operator = None
        parts = [text]

    cleaned = [part.strip(" ,.") for part in parts if part.strip(" ,.")]
    if not cleaned:
        return None

    return operator, cleaned


def _extract_sma_pair_any_direction(text: str) -> tuple[int, int] | None:
    patterns = [
        r"(\d+)\s*(?:day|d)?\s*sma\s*(?:cross(?:es)?|crossing)?\s*(?:above|below)\s*(\d+)\s*(?:day|d)?\s*sma",
        r"(\d+)\s*/\s*(\d+)\s*sma",
        r"(\d+)\s*(?:day|d)?\s+(?:and|\/)\s*(\d+)\s*(?:day|d)?\s+sma",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            fast_window = int(match.group(1))
            slow_window = int(match.group(2))
            if fast_window != slow_window:
                return fast_window, slow_window
    return None


def _build_atomic_rule_from_clause(
    clause_text: str,
    *,
    tradable_symbol: str,
    fallback_reference_symbol: str,
    side: str,
) -> tuple[dict | None, list[str]]:
    assumptions: list[str] = []
    clause_lower = clause_text.lower()

    if "rsi" in clause_lower:
        rsi_below = _extract_rsi_rule(clause_text, direction="below")
        rsi_above = _extract_rsi_rule(clause_text, direction="above")

        if rsi_below is not None:
            lookback, threshold = rsi_below
            return (
                {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": tradable_symbol,
                    "lookback": lookback,
                    "threshold": threshold,
                },
                assumptions,
            )

        if rsi_above is not None:
            lookback, threshold = rsi_above
            return (
                {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": tradable_symbol,
                    "lookback": lookback,
                    "threshold": threshold,
                },
                assumptions,
            )

        return None, assumptions

    if "moving average" in clause_lower or "sma" in clause_lower:
        pair = _extract_sma_pair_any_direction(clause_text)
        fast_window, slow_window = pair if pair else (20, 50)

        if pair is None:
            assumptions.append("Used default moving-average windows 20/50 inside a combined rule clause.")

        if "below" in clause_lower:
            rule_type = "sma_cross_below"
        elif "above" in clause_lower:
            rule_type = "sma_cross_above"
        else:
            rule_type = "sma_cross_above" if side == "entry" else "sma_cross_below"

        return (
            {
                "kind": "atomic",
                "type": rule_type,
                "symbol": tradable_symbol,
                "fast_window": fast_window,
                "slow_window": slow_window,
            },
            assumptions,
        )

    if "macd" in clause_lower:
        return (
            {
                "kind": "atomic",
                "type": "macd_bullish_cross" if side == "entry" else "macd_bearish_cross",
                "symbol": tradable_symbol,
            },
            assumptions,
        )

    if "kd" in clause_lower or "stochastic" in clause_lower:
        return (
            {
                "kind": "atomic",
                "type": "kd_golden_cross" if side == "entry" else "kd_dead_cross",
                "symbol": tradable_symbol,
            },
            assumptions,
        )

    month_values = _extract_month_values(clause_text)
    if month_values is not None and (
        "seasonality" in clause_lower or "month" in clause_lower or "months" in clause_lower
    ):
        return (
            {
                "kind": "atomic",
                "type": "month_in",
                "month_values": month_values,
            },
            assumptions,
        )

    relative_strength_rules = _extract_relative_strength_rules(
        clause_text,
        tradable_symbol=tradable_symbol,
        fallback_reference_symbol=fallback_reference_symbol,
    )
    if relative_strength_rules is not None:
        entry_rule, _, relative_strength_assumptions = relative_strength_rules
        assumptions.extend(relative_strength_assumptions)
        return entry_rule, assumptions

    return None, assumptions


def _extract_window_rule_clause(text: str) -> tuple[str, str, int] | None:
    match = re.search(
        r"^(any|all)\s+(.+?)\s+within\s+(\d+)\s+bars?$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    mode = match.group(1).upper()
    inner_clause = match.group(2).strip(" ,.")
    window_bars = int(match.group(3))
    return mode, inner_clause, window_bars


def _extract_sequence_rule_clause(text: str) -> tuple[str, str, int] | None:
    match = re.search(
        r"^(.+?)\s+then\s+(.+?)\s+within\s+(\d+)\s+bars?$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    first_clause = match.group(1).strip(" ,.")
    second_clause = match.group(2).strip(" ,.")
    window_bars = int(match.group(3))
    return first_clause, second_clause, window_bars


def _build_rule_from_clause(
    clause_text: str,
    *,
    tradable_symbol: str,
    fallback_reference_symbol: str,
    side: str,
) -> tuple[dict | None, list[str]]:
    sequence_rule = _extract_sequence_rule_clause(clause_text)
    if sequence_rule is not None:
        first_clause, second_clause, window_bars = sequence_rule

        first_rule, first_assumptions = _build_atomic_rule_from_clause(
            first_clause,
            tradable_symbol=tradable_symbol,
            fallback_reference_symbol=fallback_reference_symbol,
            side=side,
        )
        second_rule, second_assumptions = _build_atomic_rule_from_clause(
            second_clause,
            tradable_symbol=tradable_symbol,
            fallback_reference_symbol=fallback_reference_symbol,
            side=side,
        )

        if first_rule is None or second_rule is None:
            return None, []

        return (
            {
                "kind": "sequence",
                "window_bars": window_bars,
                "steps": [first_rule, second_rule],
            },
            [*first_assumptions, *second_assumptions],
        )

    window_rule = _extract_window_rule_clause(clause_text)
    if window_rule is not None:
        mode, inner_clause, window_bars = window_rule

        inner_rule, inner_assumptions = _build_rule_from_clause(
            inner_clause,
            tradable_symbol=tradable_symbol,
            fallback_reference_symbol=fallback_reference_symbol,
            side=side,
        )
        if inner_rule is None:
            return None, []

        return (
            {
                "kind": "window",
                "window_bars": window_bars,
                "mode": mode,
                "rule": inner_rule,
            },
            inner_assumptions,
        )

    split_result = _split_clause_conditions(clause_text)
    if split_result is None:
        return None, []

    operator, parts = split_result
    rules: list[dict] = []
    assumptions: list[str] = []

    for part in parts:
        rule, rule_assumptions = _build_atomic_rule_from_clause(
            part,
            tradable_symbol=tradable_symbol,
            fallback_reference_symbol=fallback_reference_symbol,
            side=side,
        )
        if rule is None:
            return None, []
        rules.append(rule)
        assumptions.extend(rule_assumptions)

    if len(rules) == 1:
        return rules[0], assumptions

    return (
        {
            "kind": "group",
            "operator": operator,
            "rules": rules,
        },
        assumptions,
    )


def _extract_confirmation_family(text: str) -> str | None:
    text_lower = text.lower()

    if "macd" in text_lower:
        return "macd"
    if "kd" in text_lower or "stochastic" in text_lower:
        return "kd"
    if (
        "relative strength" in text_lower
        or "relative return" in text_lower
        or "outperform" in text_lower
    ):
        return "relative_strength"

    return None


def _has_confirmation_add_intent(text: str) -> bool:
    return bool(
        re.search(
            r"\b(add|include|use)\b.*\b(confirmation|filter)\b|"
            r"\bwith\b.*\b(confirmation|filter)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _has_confirmation_remove_intent(text: str) -> bool:
    return bool(
        re.search(
            r"\b(remove|delete|clear|without)\b.*\b(confirmation|filter)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _build_confirmation_rules(
    text: str,
    *,
    tradable_symbol: str,
    fallback_reference_symbol: str,
) -> tuple[dict, dict, list[str]] | None:
    family = _extract_confirmation_family(text)
    if family is None:
        return None

    entry_rule, entry_assumptions = _build_atomic_rule_from_clause(
        text,
        tradable_symbol=tradable_symbol,
        fallback_reference_symbol=fallback_reference_symbol,
        side="entry",
    )
    exit_rule, exit_assumptions = _build_atomic_rule_from_clause(
        text,
        tradable_symbol=tradable_symbol,
        fallback_reference_symbol=fallback_reference_symbol,
        side="exit",
    )

    if entry_rule is None or exit_rule is None:
        return None

    label = {
        "macd": "MACD",
        "kd": "KD / stochastic",
        "relative_strength": "relative strength",
    }[family]

    assumptions = [*entry_assumptions, *exit_assumptions]
    assumptions.append(
        f"Interpreted {label} as a confirmation rule added on top of the existing draft."
    )

    return entry_rule, exit_rule, assumptions


def _add_confirmation_rule(base_rule: dict, confirmation_rule: dict) -> dict:
    if base_rule.get("kind") == "group" and base_rule.get("operator") == "AND":
        rules = list(base_rule.get("rules", []))
    else:
        rules = [base_rule]

    if any(rule == confirmation_rule for rule in rules):
        return base_rule

    return {
        "kind": "group",
        "operator": "AND",
        "rules": [*rules, confirmation_rule],
    }


def _matches_confirmation_rule(
    rule: dict,
    *,
    family: str,
    side: str,
) -> bool:
    if rule.get("kind") != "atomic":
        return False

    if family == "macd":
        expected_type = "macd_bullish_cross" if side == "entry" else "macd_bearish_cross"
        return rule.get("type") == expected_type

    if family == "kd":
        expected_type = "kd_golden_cross" if side == "entry" else "kd_dead_cross"
        return rule.get("type") == expected_type

    if family == "relative_strength":
        return rule.get("type") == "relative_return_above"

    return False


def _remove_confirmation_rule(
    base_rule: dict,
    *,
    family: str,
    side: str,
) -> dict:
    if base_rule.get("kind") != "group" or base_rule.get("operator") != "AND":
        return base_rule

    rules = list(base_rule.get("rules", []))
    filtered_rules = [
        rule
        for rule in rules
        if not _matches_confirmation_rule(rule, family=family, side=side)
    ]

    if len(filtered_rules) == len(rules):
        return base_rule

    if len(filtered_rules) == 1:
        return filtered_rules[0]

    if not filtered_rules:
        return base_rule

    return {
        "kind": "group",
        "operator": "AND",
        "rules": filtered_rules,
    }


def _extract_temporal_bars_edit(
    text: str,
    *,
    side: str,
    rule_kind: str,
) -> int | None:
    patterns = [
        rf"change\s+{side}\s+{rule_kind}\s+from\s+\d+\s+bars?\s+to\s+(\d+)\s+bars?",
        rf"change\s+{side}\s+{rule_kind}\s+to\s+(\d+)\s+bars?",
        rf"set\s+{side}\s+{rule_kind}\s+to\s+(\d+)\s+bars?",
        rf"{side}\s+{rule_kind}\s+to\s+(\d+)\s+bars?",
    ]
    return _extract_int(text, patterns)


def _extract_temporal_mode_edit(
    text: str,
    *,
    side: str,
) -> str | None:
    patterns = [
        rf"change\s+{side}\s+window\s+mode\s+to\s+(any|all)",
        rf"set\s+{side}\s+window\s+mode\s+to\s+(any|all)",
        rf"{side}\s+window\s+mode\s+(?:to\s+)?(any|all)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _extract_sequence_step_edit(
    text: str,
    *,
    side: str,
    ordinal: str,
) -> str | None:
    patterns = [
        rf"change\s+{ordinal}\s+step\s+of\s+{side}\s+sequence\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"set\s+{ordinal}\s+step\s+of\s+{side}\s+sequence\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"{side}\s+sequence\s+{ordinal}\s+step\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ,.")
    return None


def _has_temporal_rule_edit(
    *,
    entry_window_bars_edit: int | None,
    exit_window_bars_edit: int | None,
    entry_window_mode_edit: str | None,
    exit_window_mode_edit: str | None,
    entry_sequence_bars_edit: int | None,
    exit_sequence_bars_edit: int | None,
    entry_sequence_first_step_edit: str | None,
    entry_sequence_second_step_edit: str | None,
    exit_sequence_first_step_edit: str | None,
    exit_sequence_second_step_edit: str | None,
) -> bool:
    return any(
        value is not None
        for value in (
            entry_window_bars_edit,
            exit_window_bars_edit,
            entry_window_mode_edit,
            exit_window_mode_edit,
            entry_sequence_bars_edit,
            exit_sequence_bars_edit,
            entry_sequence_first_step_edit,
            entry_sequence_second_step_edit,
            exit_sequence_first_step_edit,
            exit_sequence_second_step_edit,
        )
    )


def _is_window_rule(rule: dict) -> bool:
    return rule.get("kind") == "window"


def _is_sequence_rule(rule: dict) -> bool:
    return rule.get("kind") == "sequence"


def _extract_group_operator_edit(
    text: str,
    *,
    side: str,
) -> str | None:
    patterns = [
        rf"change\s+{side}\s+group\s+operator\s+to\s+(and|or)",
        rf"set\s+{side}\s+group\s+operator\s+to\s+(and|or)",
        rf"{side}\s+group\s+operator\s+(?:to\s+)?(and|or)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _extract_group_condition_edit(
    text: str,
    *,
    side: str,
    ordinal: str,
) -> str | None:
    patterns = [
        rf"change\s+{ordinal}\s+condition\s+of\s+{side}\s+group\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"set\s+{ordinal}\s+condition\s+of\s+{side}\s+group\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"{side}\s+group\s+{ordinal}\s+condition\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ,.")
    return None


def _extract_window_inner_rule_edit(
    text: str,
    *,
    side: str,
) -> str | None:
    patterns = [
        rf"change\s+{side}\s+window\s+inner\s+rule\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"set\s+{side}\s+window\s+inner\s+rule\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"{side}\s+window\s+inner\s+rule\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ,.")
    return None


def _has_nested_composite_edit(
    *,
    entry_group_operator_edit: str | None,
    exit_group_operator_edit: str | None,
    entry_group_first_condition_edit: str | None,
    entry_group_second_condition_edit: str | None,
    exit_group_first_condition_edit: str | None,
    exit_group_second_condition_edit: str | None,
    entry_window_inner_rule_edit: str | None,
    exit_window_inner_rule_edit: str | None,
) -> bool:
    return any(
        value is not None
        for value in (
            entry_group_operator_edit,
            exit_group_operator_edit,
            entry_group_first_condition_edit,
            entry_group_second_condition_edit,
            exit_group_first_condition_edit,
            exit_group_second_condition_edit,
            entry_window_inner_rule_edit,
            exit_window_inner_rule_edit,
        )
    )


def _is_group_rule(rule: dict) -> bool:
    return rule.get("kind") == "group"


def _has_remove_group_condition_intent(
    text: str,
    *,
    side: str,
    ordinal: str,
) -> bool:
    return bool(
        re.search(
            rf"(?:remove|delete)\s+{ordinal}\s+condition\s+of\s+{side}\s+group",
            text,
            flags=re.IGNORECASE,
        )
    )


def _has_remove_window_wrapper_intent(
    text: str,
    *,
    side: str,
) -> bool:
    return bool(
        re.search(
            rf"(?:remove|delete)\s+{side}\s+window\s+wrapper",
            text,
            flags=re.IGNORECASE,
        )
    )


def _remove_group_condition(
    rule: dict,
    *,
    index: int,
) -> dict:
    if rule.get("kind") != "group":
        return rule

    rules = list(rule.get("rules", []))
    if index < 0 or index >= len(rules):
        return rule

    filtered_rules = [child for i, child in enumerate(rules) if i != index]

    if not filtered_rules:
        return rule

    if len(filtered_rules) == 1:
        return filtered_rules[0]

    updated_rule = dict(rule)
    updated_rule["rules"] = filtered_rules
    return updated_rule


def _remove_window_wrapper(rule: dict) -> dict:
    if rule.get("kind") != "window":
        return rule
    inner_rule = rule.get("rule")
    if isinstance(inner_rule, dict) and inner_rule:
        return inner_rule
    return rule


def _has_remove_sequence_step_intent(
    text: str,
    *,
    side: str,
    ordinal: str,
) -> bool:
    return bool(
        re.search(
            rf"(?:remove|delete)\s+{ordinal}\s+step\s+of\s+{side}\s+sequence",
            text,
            flags=re.IGNORECASE,
        )
    )


def _remove_sequence_step(
    rule: dict,
    *,
    index: int,
) -> dict:
    if rule.get("kind") != "sequence":
        return rule

    steps = list(rule.get("steps", []))
    if index < 0 or index >= len(steps):
        return rule

    filtered_steps = [step for i, step in enumerate(steps) if i != index]

    if not filtered_steps:
        return rule

    if len(filtered_steps) == 1:
        return filtered_steps[0]

    updated_rule = dict(rule)
    updated_rule["steps"] = filtered_steps
    return updated_rule


def _has_partial_relative_strength_edit(
    *,
    reference_symbol_edit: str | None,
    lookback_edit: int | None,
    threshold_edit: float | None,
) -> bool:
    return any(
        value is not None
        for value in (
            reference_symbol_edit,
            lookback_edit,
            threshold_edit,
        )
    )


def _is_relative_strength_entry_rule(rule: dict) -> bool:
    return (
        rule.get("kind") == "atomic"
        and rule.get("type") == "relative_return_above"
    )


def _is_relative_strength_exit_rule(rule: dict) -> bool:
    nested_rule = rule.get("rule", {})
    return (
        rule.get("kind") == "not"
        and nested_rule.get("kind") == "atomic"
        and nested_rule.get("type") == "relative_return_above"
    )


def _has_partial_sma_window_edit(
    *,
    entry_fast_window_edit: int | None,
    entry_slow_window_edit: int | None,
    exit_fast_window_edit: int | None,
    exit_slow_window_edit: int | None,
) -> bool:
    return any(
        value is not None
        for value in (
            entry_fast_window_edit,
            entry_slow_window_edit,
            exit_fast_window_edit,
            exit_slow_window_edit,
        )
    )


def _build_strategy_name(
    symbol: str,
    entry_rule: dict,
    exit_rule: dict,
) -> str:
    entry_label = _rule_label(entry_rule)
    exit_label = _rule_label(exit_rule)
    return f"{symbol.lower()}-{entry_label}-to-{exit_label}"


def _rule_label(rule: dict) -> str:
    kind = rule.get("kind")

    if kind == "atomic":
        return str(rule["type"]).replace("_", "-")

    if kind == "not":
        nested_rule = rule.get("rule", {})
        return f"not-{_rule_label(nested_rule)}"

    if kind == "group":
        operator = str(rule.get("operator", "group")).lower()
        return operator

    if kind == "window":
        nested_rule = rule.get("rule", {})
        mode = str(rule.get("mode", "window")).lower()
        return f"{mode}-window-{_rule_label(nested_rule)}"

    if kind == "sequence":
        return "sequence"

    return "rule"


def _rule_signature(rule: dict | None) -> str | None:
    if not rule:
        return None

    kind = rule.get("kind")

    if kind == "atomic":
        parts = [str(rule.get("type", "rule"))]
        for key in (
            "symbol",
            "reference_symbol",
            "lookback",
            "threshold",
            "fast_window",
            "slow_window",
            "month_values",
        ):
            value = rule.get(key)
            if value is not None:
                parts.append(f"{key}={value}")
        return "|".join(parts)

    if kind == "not":
        return f"NOT({_rule_signature(rule.get('rule', {}))})"

    if kind == "group":
        operator = str(rule.get("operator", "GROUP")).upper()
        children = ",".join(_rule_signature(child) or "rule" for child in rule.get("rules", []))
        return f"{operator}({children})"

    if kind == "window":
        return (
            f"{rule.get('mode', 'ANY')}[{rule.get('window_bars', '?')}]"
            f"({_rule_signature(rule.get('rule', {}))})"
        )

    if kind == "sequence":
        children = ",".join(_rule_signature(child) or "rule" for child in rule.get("steps", []))
        return f"SEQ[{rule.get('window_bars', '?')}]({children})"

    return str(rule)


def _merge_dict(base: dict, updates: dict) -> dict:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _extract_allocation_value_edit(text: str) -> float | None:
    patterns = [
        r"change\s+allocation\s+to\s+(\d+(?:\.\d+)?)%",
        r"set\s+allocation\s+to\s+(\d+(?:\.\d+)?)%",
        r"(?<!core\s)allocation\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
        r"allocate\s+(\d+(?:\.\d+)?)%",
        r"(\d+(?:\.\d+)?)%\s+of\s+equity",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1)) / 100.0
            return min(max(value, 0.01), 1.0)
    return None


def _has_stop_loss_removal(text: str) -> bool:
    return bool(
        re.search(
            r"(?:remove|clear|delete|disable|no)\s+stop\s+loss|without\s+stop\s+loss",
            text,
            flags=re.IGNORECASE,
        )
    )


def _has_take_profit_removal(text: str) -> bool:
    return bool(
        re.search(
            r"(?:remove|clear|delete|disable|no)\s+take\s+profit|without\s+take\s+profit",
            text,
            flags=re.IGNORECASE,
        )
    )


def _extract_cooldown_edit(text: str) -> int | None:
    return _extract_int(
        text,
        [
            r"change\s+cooldown\s+to\s+(\d+)\s+bars?",
            r"set\s+cooldown\s+to\s+(\d+)\s+bars?",
            r"cooldown\s+(\d+)\s+bars?",
        ],
    )


def _has_cooldown_removal(text: str) -> bool:
    return bool(
        re.search(
            r"(?:remove|clear|delete|disable|no)\s+cooldown|without\s+cooldown",
            text,
            flags=re.IGNORECASE,
        )
    )


def _has_partial_take_profit_removal(text: str) -> bool:
    return bool(
        re.search(
            r"(?:remove|clear|delete|disable|no)\s+partial\s+take\s+profit|without\s+partial\s+take\s+profit",
            text,
            flags=re.IGNORECASE,
        )
    )


def _extract_partial_take_profit(
    text: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    assumptions: list[str] = []

    if "partial take profit" not in text.lower():
        return None, assumptions

    trigger_profit_pct = _extract_percent(
        text,
        [
            r"partial\s+take\s+profit\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
            r"partial\s+take\s+profit\s+trigger\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
        ],
    )
    if trigger_profit_pct is None:
        trigger_profit_pct = 0.10
        assumptions.append("Used 10.0% trigger for partial take profit by default.")

    sell_fraction_of_position = _extract_percent(
        text,
        [
            r"sell\s+(\d+(?:\.\d+)?)%",
            r"reduce\s+(\d+(?:\.\d+)?)%",
        ],
    )
    if sell_fraction_of_position is None:
        sell_fraction_of_position = 0.50
        assumptions.append("Used 50.0% sell fraction for partial take profit by default.")

    max_triggers = _extract_int(
        text,
        [
            r"max\s+(\d+)\s+times?",
            r"max\s+triggers?\s+(\d+)",
        ],
    )
    if max_triggers is None:
        max_triggers = 1
        assumptions.append("Used max 1 trigger for partial take profit by default.")

    return (
        {
            "trigger_profit_pct": trigger_profit_pct,
            "sell_fraction_of_position": sell_fraction_of_position,
            "max_triggers": max_triggers,
        },
        assumptions,
    )


def _extract_scale_in_fraction_edit(text: str) -> float | None:
    return _extract_percent(
        text,
        [
            r"scale\s+in\s+(?:to|at)\s+(\d+(?:\.\d+)?)%",
            r"set\s+scale\s+in\s+to\s+(\d+(?:\.\d+)?)%",
        ],
    )


def _extract_scale_out_fraction_edit(text: str) -> float | None:
    return _extract_percent(
        text,
        [
            r"scale\s+out\s+(?:to|at)\s+(\d+(?:\.\d+)?)%",
            r"set\s+scale\s+out\s+to\s+(\d+(?:\.\d+)?)%",
        ],
    )


def _extract_profit_reduce_threshold_edit(text: str) -> float | None:
    return _extract_percent(
        text,
        [
            r"profit\s+reduce\s+threshold\s+(?:to|at)\s+(\d+(?:\.\d+)?)%",
            r"set\s+profit\s+reduce\s+threshold\s+to\s+(\d+(?:\.\d+)?)%",
        ],
    )


def _has_position_management_removal(text: str) -> bool:
    return bool(
        re.search(
            r"(?:remove|clear|delete|disable|no)\s+position\s+management|without\s+position\s+management",
            text,
            flags=re.IGNORECASE,
        )
    )


def _build_position_management(
    *,
    existing: dict[str, Any] | None,
    scale_in_fraction: float | None,
    scale_out_fraction: float | None,
    profit_reduce_threshold: float | None,
) -> dict[str, Any] | None:
    if (
        scale_in_fraction is None
        and scale_out_fraction is None
        and profit_reduce_threshold is None
        and existing is None
    ):
        return None

    base = dict(
        existing
        or {
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "profit_reduce_threshold": 0.05,
        }
    )

    if scale_in_fraction is not None:
        base["scale_in_fraction"] = scale_in_fraction
    if scale_out_fraction is not None:
        base["scale_out_fraction"] = scale_out_fraction
    if profit_reduce_threshold is not None:
        base["profit_reduce_threshold"] = profit_reduce_threshold

    return base


def _extract_core_allocation_pct(text: str) -> float | None:
    return _extract_percent(
        text,
        [
            r"core\s+allocation\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
            r"enable\s+core\s+allocation\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
            r"core\s+overlay\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
        ],
    )


def _has_core_overlay_disable(text: str) -> bool:
    return bool(
        re.search(
            r"(?:disable|remove|clear|delete|no)\s+core\s+(?:allocation|overlay)|without\s+core\s+(?:allocation|overlay)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _has_core_overlay_enable(text: str) -> bool:
    return bool(
        re.search(
            r"enable\s+core\s+(?:allocation|overlay)|core\s+(?:allocation|overlay)\s+(?:at|to)\s+\d+(?:\.\d+)?%",
            text,
            flags=re.IGNORECASE,
        )
    )


def _format_enabled(value: Any) -> str:
    return "enabled" if bool(value) else "disabled"


def _format_pct(value: Any) -> str:
    if value is None:
        return "none"
    return f"{float(value) * 100:.1f}%"


def _format_month_values(value: Any) -> str:
    if not value:
        return "none"
    return ", ".join(str(month) for month in value)


def _record_change(changes: list[str], before: Any, after: Any, label: str, formatter=str) -> None:
    if before == after:
        return
    changes.append(f"Updated {label} from {formatter(before)} to {formatter(after)}.")


def _summarize_changes(base_config: dict[str, Any], config: dict[str, Any]) -> list[str]:
    changes: list[str] = []

    if not base_config:
        return changes

    base_risk = base_config.get("risk", {}) or {}
    final_risk = config.get("risk", {}) or {}
    base_allocation = base_config.get("allocation", {}) or {}
    final_allocation = config.get("allocation", {}) or {}
    base_entry = base_config.get("entry_rule", {}) or {}
    final_entry = config.get("entry_rule", {}) or {}
    base_exit = base_config.get("exit_rule", {}) or {}
    final_exit = config.get("exit_rule", {}) or {}
    base_exit_nested = base_exit.get("rule", {}) if base_exit.get("kind") == "not" else {}
    final_exit_nested = final_exit.get("rule", {}) if final_exit.get("kind") == "not" else {}
    base_partial_take_profit = base_risk.get("partial_take_profit", {}) or {}
    final_partial_take_profit = final_risk.get("partial_take_profit", {}) or {}
    base_position_management = base_config.get("position_management", {}) or {}
    final_position_management = config.get("position_management", {}) or {}
    base_core_overlay = base_config.get("core_overlay", {}) or {}
    final_core_overlay = config.get("core_overlay", {}) or {}

    _record_change(
        changes,
        base_config.get("tradable_symbol"),
        config.get("tradable_symbol"),
        "tradable symbol",
    )
    _record_change(
        changes,
        base_risk.get("stop_loss_pct"),
        final_risk.get("stop_loss_pct"),
        "stop loss",
        _format_pct,
    )
    _record_change(
        changes,
        base_risk.get("take_profit_pct"),
        final_risk.get("take_profit_pct"),
        "take profit",
        _format_pct,
    )
    _record_change(
        changes,
        base_allocation.get("entry_value"),
        final_allocation.get("entry_value"),
        "allocation",
        _format_pct,
    )
    _record_change(
        changes,
        base_config.get("benchmark_symbol"),
        config.get("benchmark_symbol"),
        "benchmark",
    )
    _record_change(
        changes,
        base_risk.get("cooldown_bars", 0),
        final_risk.get("cooldown_bars", 0),
        "cooldown bars",
    )
    _record_change(
        changes,
        base_partial_take_profit.get("trigger_profit_pct"),
        final_partial_take_profit.get("trigger_profit_pct"),
        "partial take profit trigger",
        _format_pct,
    )
    _record_change(
        changes,
        base_partial_take_profit.get("sell_fraction_of_position"),
        final_partial_take_profit.get("sell_fraction_of_position"),
        "partial take profit sell fraction",
        _format_pct,
    )
    _record_change(
        changes,
        base_partial_take_profit.get("max_triggers"),
        final_partial_take_profit.get("max_triggers"),
        "partial take profit max triggers",
    )
    _record_change(
        changes,
        base_entry.get("threshold"),
        final_entry.get("threshold"),
        "entry threshold",
    )
    _record_change(
        changes,
        base_exit.get("threshold"),
        final_exit.get("threshold"),
        "exit threshold",
    )
    _record_change(
        changes,
        _rule_signature(base_entry),
        _rule_signature(final_entry),
        "entry rule",
    )
    _record_change(
        changes,
        _rule_signature(base_exit),
        _rule_signature(final_exit),
        "exit rule",
    )
    _record_change(
        changes,
        base_entry.get("fast_window"),
        final_entry.get("fast_window"),
        "entry fast window",
    )
    _record_change(
        changes,
        base_entry.get("slow_window"),
        final_entry.get("slow_window"),
        "entry slow window",
    )
    _record_change(
        changes,
        base_exit.get("fast_window"),
        final_exit.get("fast_window"),
        "exit fast window",
    )
    _record_change(
        changes,
        base_exit.get("slow_window"),
        final_exit.get("slow_window"),
        "exit slow window",
    )
    _record_change(
        changes,
        base_entry.get("month_values"),
        final_entry.get("month_values"),
        "seasonality months",
        _format_month_values,
    )

    if base_entry.get("kind") == "group" and final_entry.get("kind") == "group":
        _record_change(
            changes,
            base_entry.get("operator"),
            final_entry.get("operator"),
            "entry group operator",
        )
        _record_change(
            changes,
            _rule_signature((base_entry.get("rules") or [None, None])[0]),
            _rule_signature((final_entry.get("rules") or [None, None])[0]),
            "entry group first condition",
        )
        _record_change(
            changes,
            _rule_signature((base_entry.get("rules") or [None, None])[1]),
            _rule_signature((final_entry.get("rules") or [None, None])[1]),
            "entry group second condition",
        )

    if base_entry.get("kind") == "window" and final_entry.get("kind") == "window":
        _record_change(
            changes,
            base_entry.get("window_bars"),
            final_entry.get("window_bars"),
            "entry window bars",
        )
        _record_change(
            changes,
            base_entry.get("mode"),
            final_entry.get("mode"),
            "entry window mode",
        )
        _record_change(
            changes,
            _rule_signature(base_entry.get("rule")),
            _rule_signature(final_entry.get("rule")),
            "entry window inner rule",
        )

    if base_exit.get("kind") == "group" and final_exit.get("kind") == "group":
        _record_change(
            changes,
            base_exit.get("operator"),
            final_exit.get("operator"),
            "exit group operator",
        )
        _record_change(
            changes,
            _rule_signature((base_exit.get("rules") or [None, None])[0]),
            _rule_signature((final_exit.get("rules") or [None, None])[0]),
            "exit group first condition",
        )
        _record_change(
            changes,
            _rule_signature((base_exit.get("rules") or [None, None])[1]),
            _rule_signature((final_exit.get("rules") or [None, None])[1]),
            "exit group second condition",
        )

    if base_exit.get("kind") == "window" and final_exit.get("kind") == "window":
        _record_change(
            changes,
            base_exit.get("window_bars"),
            final_exit.get("window_bars"),
            "exit window bars",
        )
        _record_change(
            changes,
            base_exit.get("mode"),
            final_exit.get("mode"),
            "exit window mode",
        )
        _record_change(
            changes,
            _rule_signature(base_exit.get("rule")),
            _rule_signature(final_exit.get("rule")),
            "exit window inner rule",
        )

    if base_entry.get("kind") == "sequence" and final_entry.get("kind") == "sequence":
        _record_change(
            changes,
            base_entry.get("window_bars"),
            final_entry.get("window_bars"),
            "entry sequence bars",
        )
        _record_change(
            changes,
            _rule_signature((base_entry.get("steps") or [None, None])[0]),
            _rule_signature((final_entry.get("steps") or [None, None])[0]),
            "entry sequence first step",
        )
        _record_change(
            changes,
            _rule_signature((base_entry.get("steps") or [None, None])[1]),
            _rule_signature((final_entry.get("steps") or [None, None])[1]),
            "entry sequence second step",
        )

    if base_exit.get("kind") == "sequence" and final_exit.get("kind") == "sequence":
        _record_change(
            changes,
            base_exit.get("window_bars"),
            final_exit.get("window_bars"),
            "exit sequence bars",
        )
        _record_change(
            changes,
            _rule_signature((base_exit.get("steps") or [None, None])[0]),
            _rule_signature((final_exit.get("steps") or [None, None])[0]),
            "exit sequence first step",
        )
        _record_change(
            changes,
            _rule_signature((base_exit.get("steps") or [None, None])[1]),
            _rule_signature((final_exit.get("steps") or [None, None])[1]),
            "exit sequence second step",
        )

    _record_change(
        changes,
        base_position_management.get("scale_in_fraction"),
        final_position_management.get("scale_in_fraction"),
        "scale in fraction",
        _format_pct,
    )
    _record_change(
        changes,
        base_position_management.get("scale_out_fraction"),
        final_position_management.get("scale_out_fraction"),
        "scale out fraction",
        _format_pct,
    )
    _record_change(
        changes,
        base_position_management.get("profit_reduce_threshold"),
        final_position_management.get("profit_reduce_threshold"),
        "profit reduce threshold",
        _format_pct,
    )
    _record_change(
        changes,
        base_core_overlay.get("enabled", False),
        final_core_overlay.get("enabled", False),
        "core allocation",
        _format_enabled,
    )
    _record_change(
        changes,
        base_core_overlay.get("core_allocation_pct", 0.0),
        final_core_overlay.get("core_allocation_pct", 0.0),
        "core allocation percentage",
        _format_pct,
    )
    _record_change(
        changes,
        base_entry.get("reference_symbol"),
        final_entry.get("reference_symbol"),
        "relative strength reference symbol",
    )
    _record_change(
        changes,
        base_entry.get("lookback"),
        final_entry.get("lookback"),
        "relative strength lookback",
    )
    _record_change(
        changes,
        base_entry.get("threshold"),
        final_entry.get("threshold"),
        "relative strength threshold",
        _format_pct,
    )

    if base_exit_nested or final_exit_nested:
        _record_change(
            changes,
            base_exit_nested.get("reference_symbol"),
            final_exit_nested.get("reference_symbol"),
            "relative strength exit reference symbol",
        )
        _record_change(
            changes,
            base_exit_nested.get("lookback"),
            final_exit_nested.get("lookback"),
            "relative strength exit lookback",
        )
        _record_change(
            changes,
            base_exit_nested.get("threshold"),
            final_exit_nested.get("threshold"),
            "relative strength exit threshold",
            _format_pct,
        )

    return changes


def _build_summary_intro(
    *,
    symbol: str,
    start_date_str: str,
    end_date_str: str,
    assumptions: list[str],
) -> str:
    if any(
        assumption.startswith(f"Used available history for {symbol} ")
        for assumption in assumptions
    ):
        return (
            f"Drafted a strategy for {symbol} using available history "
            f"from {start_date_str} to {end_date_str}"
        )

    if any(
        assumption == f"No ETF metadata was found for {symbol}, so the default platform backtest range was used."
        for assumption in assumptions
    ):
        return (
            f"Drafted a strategy for {symbol} using the default platform range "
            f"from {start_date_str} to {end_date_str}"
        )

    return f"Drafted a strategy for {symbol} from {start_date_str} to {end_date_str}"


def _generate_strategy_draft(
    req: StrategyBuilderGenerateRequest,
    *,
    max_backtest_years: int,
) -> tuple[dict, str, list[str], list[str], list[str]]:
    prompt = req.prompt.strip()
    prompt_lower = prompt.lower()

    warnings: list[str] = []
    assumptions: list[str] = []

    current_config = req.context.current_config if req.context else None
    has_current_config = isinstance(current_config, dict) and bool(current_config)

    tradable_symbol, symbol_assumptions = _extract_primary_symbol(prompt)
    if has_current_config and symbol_assumptions:
        assumptions.append("No tradable symbol detected in prompt; existing config may be reused.")
    else:
        assumptions.extend(symbol_assumptions)

    benchmark_symbol, benchmark_assumptions = _extract_benchmark_symbol(
        prompt,
        tradable_symbol,
    )
    tradable_symbol_edit = _extract_tradable_symbol_edit(prompt)
    assumptions.extend(benchmark_assumptions)

    reference_symbols = _extract_reference_symbols(
        prompt,
        tradable_symbol,
        benchmark_symbol,
    )
    if reference_symbols:
        assumptions.append(
            f"Detected reference symbols: {', '.join(reference_symbols)}."
        )

    start_date, end_date, date_assumptions = _extract_date_range(
        prompt,
        symbol=tradable_symbol,
        max_backtest_years=max_backtest_years,
    )
    assumptions.extend(date_assumptions)

    initial_capital, capital_assumptions = _extract_initial_capital(prompt)
    assumptions.extend(capital_assumptions)

    allocation_edit_value = _extract_allocation_value_edit(prompt)
    allocation_value, allocation_assumptions = _extract_allocation_value(prompt)
    explicit_date_edits = _extract_explicit_date_edits(prompt)
    assumptions.extend(allocation_assumptions)

    stop_loss_removed = _has_stop_loss_removal(prompt)
    stop_loss_pct = None if stop_loss_removed else _extract_percent(
        prompt,
        [
            r"stop\s+loss\s+(?:at\s+|to\s+)?(\d+(?:\.\d+)?)%",
            r"(\d+(?:\.\d+)?)%\s+stop\s+loss",
        ],
    )
    if stop_loss_pct is None and not stop_loss_removed:
        assumptions.append("No stop loss was specified.")

    take_profit_removed = _has_take_profit_removal(prompt)
    take_profit_pct = None if take_profit_removed else _extract_percent(
        prompt,
        [
            r"(?<!partial\s)take\s+profit\s+(?:at\s+|to\s+)?(\d+(?:\.\d+)?)%",
            r"(\d+(?:\.\d+)?)%\s+take\s+profit",
        ],
    )
    if take_profit_pct is None and not take_profit_removed:
        assumptions.append("No take profit was specified.")

    cooldown_removed = _has_cooldown_removal(prompt)
    cooldown_edit = _extract_cooldown_edit(prompt)
    cooldown_bars = 0 if cooldown_removed else cooldown_edit
    if cooldown_bars is None:
        cooldown_bars = 0
        assumptions.append("Used cooldown of 0 bars by default.")

    partial_take_profit_removed = _has_partial_take_profit_removal(prompt)
    partial_take_profit, partial_take_profit_assumptions = (
        (None, [])
        if partial_take_profit_removed
        else _extract_partial_take_profit(prompt)
    )
    assumptions.extend(partial_take_profit_assumptions)

    scale_in_fraction_edit = _extract_scale_in_fraction_edit(prompt)
    scale_out_fraction_edit = _extract_scale_out_fraction_edit(prompt)
    profit_reduce_threshold_edit = _extract_profit_reduce_threshold_edit(prompt)
    position_management_removed = _has_position_management_removal(prompt)
    has_position_management_edit = (
        position_management_removed
        or scale_in_fraction_edit is not None
        or scale_out_fraction_edit is not None
        or profit_reduce_threshold_edit is not None
    )

    core_allocation_pct = _extract_core_allocation_pct(prompt)
    core_overlay_disabled = _has_core_overlay_disable(prompt)
    core_overlay_enabled = _has_core_overlay_enable(prompt) or core_allocation_pct is not None

    entry_rule = None
    exit_rule = None

    rsi_buy = _extract_rsi_rule(prompt, direction="below")
    rsi_sell = _extract_rsi_rule(prompt, direction="above")
    rsi_entry_threshold_edit = _extract_rsi_entry_threshold_edit(prompt)
    rsi_exit_threshold_edit = _extract_rsi_exit_threshold_edit(prompt)
    sma_pair = _extract_sma_crossover_pair(prompt)

    entry_fast_window_edit = _extract_entry_fast_window_edit(prompt)
    entry_slow_window_edit = _extract_entry_slow_window_edit(prompt)
    exit_fast_window_edit = _extract_exit_fast_window_edit(prompt)
    exit_slow_window_edit = _extract_exit_slow_window_edit(prompt)

    has_partial_sma_window_edit = _has_partial_sma_window_edit(
        entry_fast_window_edit=entry_fast_window_edit,
        entry_slow_window_edit=entry_slow_window_edit,
        exit_fast_window_edit=exit_fast_window_edit,
        exit_slow_window_edit=exit_slow_window_edit,
    )

    if rsi_buy:
        lookback, threshold = rsi_buy
        entry_rule = {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": tradable_symbol,
            "lookback": lookback,
            "threshold": threshold,
        }

    if rsi_sell:
        lookback, threshold = rsi_sell
        exit_rule = {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": tradable_symbol,
            "lookback": lookback,
            "threshold": threshold,
        }

    if "moving average" in prompt_lower or "sma" in prompt_lower:
        fast_window, slow_window = sma_pair if sma_pair else (20, 50)
        if sma_pair:
            assumptions.append(
                f"Detected moving-average windows {fast_window}/{slow_window}."
            )
        else:
            assumptions.append(
                "Used default moving-average windows 20/50."
            )

        if entry_rule is None:
            entry_rule = {
                "kind": "atomic",
                "type": "sma_cross_above",
                "symbol": tradable_symbol,
                "fast_window": fast_window,
                "slow_window": slow_window,
            }

        if exit_rule is None:
            exit_rule = {
                "kind": "atomic",
                "type": "sma_cross_below",
                "symbol": tradable_symbol,
                "fast_window": fast_window,
                "slow_window": slow_window,
            }

    if "macd" in prompt_lower:
        entry_rule = {
            "kind": "atomic",
            "type": "macd_bullish_cross",
            "symbol": tradable_symbol,
        }
        exit_rule = {
            "kind": "atomic",
            "type": "macd_bearish_cross",
            "symbol": tradable_symbol,
        }
        assumptions.append(
            "Interpreted 'MACD' as MACD bullish cross for entry and MACD bearish cross for exit."
        )

    if "kd" in prompt_lower or "stochastic" in prompt_lower:
        entry_rule = {
            "kind": "atomic",
            "type": "kd_golden_cross",
            "symbol": tradable_symbol,
        }
        exit_rule = {
            "kind": "atomic",
            "type": "kd_dead_cross",
            "symbol": tradable_symbol,
        }
        assumptions.append(
            "Interpreted 'KD' as KD golden cross for entry and KD dead cross for exit."
        )

    month_values = _extract_month_values(prompt)

    relative_strength_reference_symbol_edit = _extract_relative_strength_reference_symbol_edit(prompt)
    relative_strength_lookback_edit = _extract_relative_strength_lookback_edit(prompt)
    relative_strength_threshold_edit = _extract_relative_strength_threshold_edit(prompt)

    has_partial_relative_strength_edit = _has_partial_relative_strength_edit(
        reference_symbol_edit=relative_strength_reference_symbol_edit,
        lookback_edit=relative_strength_lookback_edit,
        threshold_edit=relative_strength_threshold_edit,
    )

    confirmation_family = _extract_confirmation_family(prompt)
    add_confirmation_intent = _has_confirmation_add_intent(prompt)
    remove_confirmation_intent = _has_confirmation_remove_intent(prompt)
    has_confirmation_edit_intent = (
        confirmation_family is not None
        and (add_confirmation_intent or remove_confirmation_intent)
    )

    entry_window_bars_edit = _extract_temporal_bars_edit(
        prompt,
        side="entry",
        rule_kind="window",
    )
    exit_window_bars_edit = _extract_temporal_bars_edit(
        prompt,
        side="exit",
        rule_kind="window",
    )
    entry_window_mode_edit = _extract_temporal_mode_edit(
        prompt,
        side="entry",
    )
    exit_window_mode_edit = _extract_temporal_mode_edit(
        prompt,
        side="exit",
    )
    entry_sequence_bars_edit = _extract_temporal_bars_edit(
        prompt,
        side="entry",
        rule_kind="sequence",
    )
    exit_sequence_bars_edit = _extract_temporal_bars_edit(
        prompt,
        side="exit",
        rule_kind="sequence",
    )
    entry_sequence_first_step_edit = _extract_sequence_step_edit(
        prompt,
        side="entry",
        ordinal="first",
    )
    entry_sequence_second_step_edit = _extract_sequence_step_edit(
        prompt,
        side="entry",
        ordinal="second",
    )
    exit_sequence_first_step_edit = _extract_sequence_step_edit(
        prompt,
        side="exit",
        ordinal="first",
    )
    exit_sequence_second_step_edit = _extract_sequence_step_edit(
        prompt,
        side="exit",
        ordinal="second",
    )

    has_temporal_rule_edit_intent = _has_temporal_rule_edit(
        entry_window_bars_edit=entry_window_bars_edit,
        exit_window_bars_edit=exit_window_bars_edit,
        entry_window_mode_edit=entry_window_mode_edit,
        exit_window_mode_edit=exit_window_mode_edit,
        entry_sequence_bars_edit=entry_sequence_bars_edit,
        exit_sequence_bars_edit=exit_sequence_bars_edit,
        entry_sequence_first_step_edit=entry_sequence_first_step_edit,
        entry_sequence_second_step_edit=entry_sequence_second_step_edit,
        exit_sequence_first_step_edit=exit_sequence_first_step_edit,
        exit_sequence_second_step_edit=exit_sequence_second_step_edit,
    )

    entry_group_operator_edit = _extract_group_operator_edit(
        prompt,
        side="entry",
    )
    exit_group_operator_edit = _extract_group_operator_edit(
        prompt,
        side="exit",
    )
    entry_group_first_condition_edit = _extract_group_condition_edit(
        prompt,
        side="entry",
        ordinal="first",
    )
    entry_group_second_condition_edit = _extract_group_condition_edit(
        prompt,
        side="entry",
        ordinal="second",
    )
    exit_group_first_condition_edit = _extract_group_condition_edit(
        prompt,
        side="exit",
        ordinal="first",
    )
    exit_group_second_condition_edit = _extract_group_condition_edit(
        prompt,
        side="exit",
        ordinal="second",
    )
    entry_window_inner_rule_edit = _extract_window_inner_rule_edit(
        prompt,
        side="entry",
    )
    exit_window_inner_rule_edit = _extract_window_inner_rule_edit(
        prompt,
        side="exit",
    )

    has_nested_composite_edit_intent = _has_nested_composite_edit(
        entry_group_operator_edit=entry_group_operator_edit,
        exit_group_operator_edit=exit_group_operator_edit,
        entry_group_first_condition_edit=entry_group_first_condition_edit,
        entry_group_second_condition_edit=entry_group_second_condition_edit,
        exit_group_first_condition_edit=exit_group_first_condition_edit,
        exit_group_second_condition_edit=exit_group_second_condition_edit,
        entry_window_inner_rule_edit=entry_window_inner_rule_edit,
        exit_window_inner_rule_edit=exit_window_inner_rule_edit,
    )

    remove_entry_group_first_condition = _has_remove_group_condition_intent(
        prompt,
        side="entry",
        ordinal="first",
    )
    remove_entry_group_second_condition = _has_remove_group_condition_intent(
        prompt,
        side="entry",
        ordinal="second",
    )
    remove_exit_group_first_condition = _has_remove_group_condition_intent(
        prompt,
        side="exit",
        ordinal="first",
    )
    remove_exit_group_second_condition = _has_remove_group_condition_intent(
        prompt,
        side="exit",
        ordinal="second",
    )
    remove_entry_window_wrapper = _has_remove_window_wrapper_intent(
        prompt,
        side="entry",
    )
    remove_exit_window_wrapper = _has_remove_window_wrapper_intent(
        prompt,
        side="exit",
    )

    remove_entry_sequence_first_step = _has_remove_sequence_step_intent(
        prompt,
        side="entry",
        ordinal="first",
    )
    remove_entry_sequence_second_step = _has_remove_sequence_step_intent(
        prompt,
        side="entry",
        ordinal="second",
    )
    remove_exit_sequence_first_step = _has_remove_sequence_step_intent(
        prompt,
        side="exit",
        ordinal="first",
    )
    remove_exit_sequence_second_step = _has_remove_sequence_step_intent(
        prompt,
        side="exit",
        ordinal="second",
    )

    has_nested_composite_removal_intent = any(
        (
            remove_entry_group_first_condition,
            remove_entry_group_second_condition,
            remove_exit_group_first_condition,
            remove_exit_group_second_condition,
            remove_entry_window_wrapper,
            remove_exit_window_wrapper,
            remove_entry_sequence_first_step,
            remove_entry_sequence_second_step,
            remove_exit_sequence_first_step,
            remove_exit_sequence_second_step,
        )
    )

    if has_confirmation_edit_intent and not has_current_config:
        raise ValueError(
            "Confirmation filters currently require an existing draft. "
            "Create a base strategy first, then ask me to add or remove "
            "MACD, KD/stochastic, or relative strength confirmation."
        )

    if (
        ("seasonality" in prompt_lower or "month" in prompt_lower or "months" in prompt_lower)
        and month_values is not None
    ):
        entry_rule = {
            "kind": "atomic",
            "type": "month_in",
            "month_values": month_values,
        }
        exit_rule = {
            "kind": "not",
            "rule": {
                "kind": "atomic",
                "type": "month_in",
                "month_values": month_values,
            },
        }
        assumptions.append(
            "Interpreted seasonality/month language as entering only during the selected calendar months."
        )

    relative_strength_rules = _extract_relative_strength_rules(
        prompt,
        tradable_symbol=(
            current_config.get("tradable_symbol", tradable_symbol)
            if has_current_config
            else tradable_symbol
        ),
        fallback_reference_symbol=(
            current_config.get("benchmark_symbol", benchmark_symbol)
            if has_current_config
            else benchmark_symbol
        ),
    )
    if relative_strength_rules is not None:
        entry_rule, exit_rule, relative_strength_assumptions = relative_strength_rules
        assumptions.extend(relative_strength_assumptions)

    confirmation_rules = None
    if has_confirmation_edit_intent:
        confirmation_rules = _build_confirmation_rules(
            prompt,
            tradable_symbol=(
                current_config.get("tradable_symbol", tradable_symbol)
                if has_current_config
                else tradable_symbol
            ),
            fallback_reference_symbol=(
                current_config.get("benchmark_symbol", benchmark_symbol)
                if has_current_config
                else benchmark_symbol
            ),
        )
        if confirmation_rules is None:
            raise ValueError(
                "I could not deterministically parse that confirmation filter. "
                "Supported confirmation filters right now are MACD, KD/stochastic, and relative strength."
            )

        _, _, confirmation_assumptions = confirmation_rules
        assumptions.extend(confirmation_assumptions)

    entry_clause, exit_clause = _extract_entry_exit_rule_clauses(prompt)
    if entry_clause is not None and exit_clause is not None:
        composite_entry_rule, composite_entry_assumptions = _build_rule_from_clause(
            entry_clause,
            tradable_symbol=(
                current_config.get("tradable_symbol", tradable_symbol)
                if has_current_config
                else tradable_symbol
            ),
            fallback_reference_symbol=(
                current_config.get("benchmark_symbol", benchmark_symbol)
                if has_current_config
                else benchmark_symbol
            ),
            side="entry",
        )
        composite_exit_rule, composite_exit_assumptions = _build_rule_from_clause(
            exit_clause,
            tradable_symbol=(
                current_config.get("tradable_symbol", tradable_symbol)
                if has_current_config
                else tradable_symbol
            ),
            fallback_reference_symbol=(
                current_config.get("benchmark_symbol", benchmark_symbol)
                if has_current_config
                else benchmark_symbol
            ),
            side="exit",
        )

        if composite_entry_rule is None or composite_exit_rule is None:
            raise ValueError(
                "I could not deterministically parse that combined entry/exit rule request. "
                "Use explicit clauses like 'entry when RSI below 30 and MACD' and "
                "'exit when RSI above 70 or MACD'."
            )

        entry_rule = composite_entry_rule
        exit_rule = composite_exit_rule
        assumptions.extend(composite_entry_assumptions)
        assumptions.extend(composite_exit_assumptions)
        assumptions.append(
            "Interpreted explicit entry/exit clauses as combined rules using AND/OR."
        )

    if "mean reversion" in prompt_lower and entry_rule is None and exit_rule is None:
        entry_rule = {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 30,
        }
        exit_rule = {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 70,
        }
        assumptions.append("Interpreted 'mean reversion' as RSI(14) below 30 / above 70.")

    if entry_rule is None and not has_current_config:
        entry_rule = {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 30,
        }
        warnings.append("Entry rule defaulted to RSI(14) below 30.")

    if exit_rule is None and not has_current_config:
        exit_rule = {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 70,
        }
        warnings.append("Exit rule defaulted to RSI(14) above 70.")

    base_config = current_config if has_current_config else {}

    if has_current_config:
        assumptions.append("Used current_config as the base draft for version generation.")

    default_config = dict(base_config) if has_current_config else {}

    if not has_current_config:
        default_config["schema_version"] = "2.0"
        default_config["name"] = _build_strategy_name(tradable_symbol, entry_rule, exit_rule)
        default_config["tradable_symbol"] = tradable_symbol
        default_config["benchmark_symbol"] = benchmark_symbol
        default_config["reference_symbols"] = reference_symbols
        default_config["start_date"] = start_date.isoformat()
        default_config["end_date"] = end_date.isoformat()
        default_config["initial_capital"] = initial_capital
        default_config["transaction_cost_bps"] = 5
        default_config["allocation"] = {
            "entry_mode": "percent_of_equity",
            "entry_value": allocation_value,
            "max_position_pct": 1.0,
        }
        default_config["entry_rule"] = entry_rule
        default_config["exit_rule"] = exit_rule
        if core_overlay_enabled and core_allocation_pct is None:
            core_allocation_pct = 0.60
            assumptions.append("Used 60.0% core allocation by default.")

        default_config["risk"] = {
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "partial_take_profit": partial_take_profit,
            "cooldown_bars": cooldown_bars,
        }
        default_config["core_overlay"] = {
            "enabled": bool(core_overlay_enabled and not core_overlay_disabled),
            "core_allocation_pct": (
                core_allocation_pct
                if core_overlay_enabled and not core_overlay_disabled
                else 0.0
            ),
        }
        default_config["position_management"] = (
            None
            if position_management_removed
            else _build_position_management(
                existing=None,
                scale_in_fraction=scale_in_fraction_edit,
                scale_out_fraction=scale_out_fraction_edit,
                profit_reduce_threshold=profit_reduce_threshold_edit,
            )
        )
    else:
        default_config.setdefault("schema_version", "2.0")
        default_config.setdefault("transaction_cost_bps", 5)
        default_config.setdefault("reference_symbols", [])
        default_config.setdefault("core_overlay", {"enabled": False, "core_allocation_pct": 0.0})
        default_config.setdefault("position_management", None)

        default_config.setdefault("tradable_symbol", tradable_symbol)
        default_config.setdefault("benchmark_symbol", benchmark_symbol)
        default_config.setdefault("start_date", start_date.isoformat())
        default_config.setdefault("end_date", end_date.isoformat())
        default_config.setdefault("initial_capital", initial_capital)

        if "start_date" in explicit_date_edits:
            default_config["start_date"] = explicit_date_edits["start_date"]
        if "end_date" in explicit_date_edits:
            default_config["end_date"] = explicit_date_edits["end_date"]

        default_config.setdefault(
            "allocation",
            {
                "entry_mode": "percent_of_equity",
                "entry_value": allocation_value,
                "max_position_pct": 1.0,
            },
        )

        default_config.setdefault("entry_rule", entry_rule)
        default_config.setdefault("exit_rule", exit_rule)

        benchmark_edit_intent = _has_benchmark_edit_intent(prompt)

        if tradable_symbol_edit is not None:
            old_tradable_symbol = default_config.get("tradable_symbol", tradable_symbol)
            if tradable_symbol_edit != old_tradable_symbol:
                default_config["tradable_symbol"] = tradable_symbol_edit
                default_config["entry_rule"] = _rewrite_rule_tradable_symbol(
                    default_config.get("entry_rule", {}),
                    new_symbol=tradable_symbol_edit,
                )
                default_config["exit_rule"] = _rewrite_rule_tradable_symbol(
                    default_config.get("exit_rule", {}),
                    new_symbol=tradable_symbol_edit,
                )

                if default_config.get("benchmark_symbol") == old_tradable_symbol and not benchmark_edit_intent:
                    default_config["benchmark_symbol"] = tradable_symbol_edit

                assumptions.append(
                    f"Switched tradable symbol from {old_tradable_symbol} to {tradable_symbol_edit}."
                )

        existing_entry_rule = dict(default_config.get("entry_rule", {}))
        existing_exit_rule = dict(default_config.get("exit_rule", {}))

        if has_partial_relative_strength_edit:
            if _is_relative_strength_entry_rule(existing_entry_rule) and _is_relative_strength_exit_rule(existing_exit_rule):
                updated_entry_rule = dict(existing_entry_rule)
                updated_exit_rule = dict(existing_exit_rule)
                updated_exit_nested_rule = dict(updated_exit_rule.get("rule", {}))

                if relative_strength_reference_symbol_edit is not None:
                    updated_entry_rule["reference_symbol"] = relative_strength_reference_symbol_edit
                    updated_exit_nested_rule["reference_symbol"] = relative_strength_reference_symbol_edit

                if relative_strength_lookback_edit is not None:
                    updated_entry_rule["lookback"] = relative_strength_lookback_edit
                    updated_exit_nested_rule["lookback"] = relative_strength_lookback_edit

                if relative_strength_threshold_edit is not None:
                    updated_entry_rule["threshold"] = relative_strength_threshold_edit
                    updated_exit_nested_rule["threshold"] = relative_strength_threshold_edit

                updated_exit_rule["rule"] = updated_exit_nested_rule
                default_config["entry_rule"] = updated_entry_rule
                default_config["exit_rule"] = updated_exit_rule

                existing_entry_rule = updated_entry_rule
                existing_exit_rule = updated_exit_rule

        if has_temporal_rule_edit_intent:
            current_tradable_symbol = default_config.get("tradable_symbol", tradable_symbol)
            current_benchmark_symbol = default_config.get("benchmark_symbol", benchmark_symbol)

            if entry_window_bars_edit is not None and _is_window_rule(existing_entry_rule):
                existing_entry_rule["window_bars"] = entry_window_bars_edit
                default_config["entry_rule"] = existing_entry_rule

            if entry_window_mode_edit is not None and _is_window_rule(existing_entry_rule):
                existing_entry_rule["mode"] = entry_window_mode_edit
                default_config["entry_rule"] = existing_entry_rule

            if exit_window_bars_edit is not None and _is_window_rule(existing_exit_rule):
                existing_exit_rule["window_bars"] = exit_window_bars_edit
                default_config["exit_rule"] = existing_exit_rule

            if exit_window_mode_edit is not None and _is_window_rule(existing_exit_rule):
                existing_exit_rule["mode"] = exit_window_mode_edit
                default_config["exit_rule"] = existing_exit_rule

            if entry_sequence_bars_edit is not None and _is_sequence_rule(existing_entry_rule):
                existing_entry_rule["window_bars"] = entry_sequence_bars_edit
                default_config["entry_rule"] = existing_entry_rule

            if exit_sequence_bars_edit is not None and _is_sequence_rule(existing_exit_rule):
                existing_exit_rule["window_bars"] = exit_sequence_bars_edit
                default_config["exit_rule"] = existing_exit_rule

            if entry_sequence_first_step_edit is not None and _is_sequence_rule(existing_entry_rule):
                updated_step, step_assumptions = _build_atomic_rule_from_clause(
                    entry_sequence_first_step_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="entry",
                )
                if updated_step is not None and len(existing_entry_rule.get("steps", [])) >= 1:
                    updated_steps = list(existing_entry_rule.get("steps", []))
                    updated_steps[0] = updated_step
                    existing_entry_rule["steps"] = updated_steps
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(step_assumptions)

            if entry_sequence_second_step_edit is not None and _is_sequence_rule(existing_entry_rule):
                updated_step, step_assumptions = _build_atomic_rule_from_clause(
                    entry_sequence_second_step_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="entry",
                )
                if updated_step is not None and len(existing_entry_rule.get("steps", [])) >= 2:
                    updated_steps = list(existing_entry_rule.get("steps", []))
                    updated_steps[1] = updated_step
                    existing_entry_rule["steps"] = updated_steps
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(step_assumptions)

            if exit_sequence_first_step_edit is not None and _is_sequence_rule(existing_exit_rule):
                updated_step, step_assumptions = _build_atomic_rule_from_clause(
                    exit_sequence_first_step_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="exit",
                )
                if updated_step is not None and len(existing_exit_rule.get("steps", [])) >= 1:
                    updated_steps = list(existing_exit_rule.get("steps", []))
                    updated_steps[0] = updated_step
                    existing_exit_rule["steps"] = updated_steps
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(step_assumptions)

            if exit_sequence_second_step_edit is not None and _is_sequence_rule(existing_exit_rule):
                updated_step, step_assumptions = _build_atomic_rule_from_clause(
                    exit_sequence_second_step_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="exit",
                )
                if updated_step is not None and len(existing_exit_rule.get("steps", [])) >= 2:
                    updated_steps = list(existing_exit_rule.get("steps", []))
                    updated_steps[1] = updated_step
                    existing_exit_rule["steps"] = updated_steps
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(step_assumptions)

        if has_nested_composite_edit_intent:
            current_tradable_symbol = default_config.get("tradable_symbol", tradable_symbol)
            current_benchmark_symbol = default_config.get("benchmark_symbol", benchmark_symbol)

            if entry_group_operator_edit is not None and _is_group_rule(existing_entry_rule):
                existing_entry_rule["operator"] = entry_group_operator_edit
                default_config["entry_rule"] = existing_entry_rule

            if exit_group_operator_edit is not None and _is_group_rule(existing_exit_rule):
                existing_exit_rule["operator"] = exit_group_operator_edit
                default_config["exit_rule"] = existing_exit_rule

            if entry_group_first_condition_edit is not None and _is_group_rule(existing_entry_rule):
                updated_rule, rule_assumptions = _build_atomic_rule_from_clause(
                    entry_group_first_condition_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="entry",
                )
                if updated_rule is not None and len(existing_entry_rule.get("rules", [])) >= 1:
                    updated_rules = list(existing_entry_rule.get("rules", []))
                    updated_rules[0] = updated_rule
                    existing_entry_rule["rules"] = updated_rules
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(rule_assumptions)

            if entry_group_second_condition_edit is not None and _is_group_rule(existing_entry_rule):
                updated_rule, rule_assumptions = _build_atomic_rule_from_clause(
                    entry_group_second_condition_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="entry",
                )
                if updated_rule is not None and len(existing_entry_rule.get("rules", [])) >= 2:
                    updated_rules = list(existing_entry_rule.get("rules", []))
                    updated_rules[1] = updated_rule
                    existing_entry_rule["rules"] = updated_rules
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(rule_assumptions)

            if exit_group_first_condition_edit is not None and _is_group_rule(existing_exit_rule):
                updated_rule, rule_assumptions = _build_atomic_rule_from_clause(
                    exit_group_first_condition_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="exit",
                )
                if updated_rule is not None and len(existing_exit_rule.get("rules", [])) >= 1:
                    updated_rules = list(existing_exit_rule.get("rules", []))
                    updated_rules[0] = updated_rule
                    existing_exit_rule["rules"] = updated_rules
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(rule_assumptions)

            if exit_group_second_condition_edit is not None and _is_group_rule(existing_exit_rule):
                updated_rule, rule_assumptions = _build_atomic_rule_from_clause(
                    exit_group_second_condition_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="exit",
                )
                if updated_rule is not None and len(existing_exit_rule.get("rules", [])) >= 2:
                    updated_rules = list(existing_exit_rule.get("rules", []))
                    updated_rules[1] = updated_rule
                    existing_exit_rule["rules"] = updated_rules
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(rule_assumptions)

            if entry_window_inner_rule_edit is not None and _is_window_rule(existing_entry_rule):
                updated_rule, rule_assumptions = _build_rule_from_clause(
                    entry_window_inner_rule_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="entry",
                )
                if updated_rule is not None:
                    existing_entry_rule["rule"] = updated_rule
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(rule_assumptions)

            if exit_window_inner_rule_edit is not None and _is_window_rule(existing_exit_rule):
                updated_rule, rule_assumptions = _build_rule_from_clause(
                    exit_window_inner_rule_edit,
                    tradable_symbol=current_tradable_symbol,
                    fallback_reference_symbol=current_benchmark_symbol,
                    side="exit",
                )
                if updated_rule is not None:
                    existing_exit_rule["rule"] = updated_rule
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(rule_assumptions)

        risk = dict(default_config.get("risk", {}))
        risk.setdefault("cooldown_bars", 0)
        default_config["risk"] = risk

        if _has_benchmark_edit_intent(prompt):
            default_config["benchmark_symbol"] = benchmark_symbol

        if re.search(r"(?:capital|start with|\$)", prompt_lower):
            default_config["initial_capital"] = initial_capital

        if allocation_edit_value is not None or re.search(r"%\s+of\s+equity|allocation|allocate", prompt_lower):
            allocation = dict(default_config.get("allocation", {}))
            allocation["entry_mode"] = "percent_of_equity"
            allocation["entry_value"] = allocation_edit_value if allocation_edit_value is not None else allocation_value
            allocation.setdefault("max_position_pct", 1.0)
            default_config["allocation"] = allocation

        if entry_fast_window_edit is not None or entry_slow_window_edit is not None:
            if existing_entry_rule.get("type") in {"sma_cross_above", "sma_cross_below"}:
                if entry_fast_window_edit is not None:
                    existing_entry_rule["fast_window"] = entry_fast_window_edit
                if entry_slow_window_edit is not None:
                    existing_entry_rule["slow_window"] = entry_slow_window_edit
                default_config["entry_rule"] = existing_entry_rule

        if exit_fast_window_edit is not None or exit_slow_window_edit is not None:
            if existing_exit_rule.get("type") in {"sma_cross_above", "sma_cross_below"}:
                if exit_fast_window_edit is not None:
                    existing_exit_rule["fast_window"] = exit_fast_window_edit
                if exit_slow_window_edit is not None:
                    existing_exit_rule["slow_window"] = exit_slow_window_edit
                default_config["exit_rule"] = existing_exit_rule

        if rsi_entry_threshold_edit is not None:
            if existing_entry_rule.get("type") == "rsi_below":
                existing_entry_rule["threshold"] = rsi_entry_threshold_edit
                existing_entry_rule.setdefault("lookback", 14)
                existing_entry_rule.setdefault("kind", "atomic")
                default_config["entry_rule"] = existing_entry_rule
            else:
                default_config["entry_rule"] = {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": default_config.get("tradable_symbol", tradable_symbol),
                    "lookback": 14,
                    "threshold": rsi_entry_threshold_edit,
                }

        elif entry_rule is not None and not has_partial_sma_window_edit and not has_partial_relative_strength_edit and not has_confirmation_edit_intent and not has_temporal_rule_edit_intent and not has_nested_composite_edit_intent and not has_nested_composite_removal_intent and (
            "rsi" in prompt_lower
            or "mean reversion" in prompt_lower
            or "moving average" in prompt_lower
            or "sma" in prompt_lower
            or "macd" in prompt_lower
            or "kd" in prompt_lower
            or "stochastic" in prompt_lower
            or "seasonality" in prompt_lower
            or "month" in prompt_lower
            or "months" in prompt_lower
            or "relative strength" in prompt_lower
            or "relative return" in prompt_lower
            or "outperform" in prompt_lower
        ):
            default_config["entry_rule"] = entry_rule

        if rsi_exit_threshold_edit is not None:
            if existing_exit_rule.get("type") == "rsi_above":
                existing_exit_rule["threshold"] = rsi_exit_threshold_edit
                existing_exit_rule.setdefault("lookback", 14)
                existing_exit_rule.setdefault("kind", "atomic")
                default_config["exit_rule"] = existing_exit_rule
            else:
                default_config["exit_rule"] = {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": default_config.get("tradable_symbol", tradable_symbol),
                    "lookback": 14,
                    "threshold": rsi_exit_threshold_edit,
                }

        elif exit_rule is not None and not has_partial_sma_window_edit and not has_partial_relative_strength_edit and not has_confirmation_edit_intent and not has_temporal_rule_edit_intent and not has_nested_composite_edit_intent and not has_nested_composite_removal_intent and (
            "rsi" in prompt_lower
            or "mean reversion" in prompt_lower
            or "moving average" in prompt_lower
            or "sma" in prompt_lower
            or "macd" in prompt_lower
            or "kd" in prompt_lower
            or "stochastic" in prompt_lower
            or "seasonality" in prompt_lower
            or "month" in prompt_lower
            or "months" in prompt_lower
            or "relative strength" in prompt_lower
            or "relative return" in prompt_lower
            or "outperform" in prompt_lower
        ):
            default_config["exit_rule"] = exit_rule

        if has_confirmation_edit_intent:
            current_entry_rule = dict(default_config.get("entry_rule", {}))
            current_exit_rule = dict(default_config.get("exit_rule", {}))

            if add_confirmation_intent and confirmation_rules is not None:
                entry_confirmation_rule, exit_confirmation_rule, _ = confirmation_rules
                default_config["entry_rule"] = _add_confirmation_rule(
                    current_entry_rule,
                    entry_confirmation_rule,
                )
                default_config["exit_rule"] = _add_confirmation_rule(
                    current_exit_rule,
                    exit_confirmation_rule,
                )

            elif remove_confirmation_intent and confirmation_family is not None:
                default_config["entry_rule"] = _remove_confirmation_rule(
                    current_entry_rule,
                    family=confirmation_family,
                    side="entry",
                )
                default_config["exit_rule"] = _remove_confirmation_rule(
                    current_exit_rule,
                    family=confirmation_family,
                    side="exit",
                )

        if has_nested_composite_removal_intent:
            if remove_entry_group_first_condition:
                updated_entry_rule = _remove_group_condition(existing_entry_rule, index=0)
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

            if remove_entry_group_second_condition:
                updated_entry_rule = _remove_group_condition(existing_entry_rule, index=1)
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

            if remove_exit_group_first_condition:
                updated_exit_rule = _remove_group_condition(existing_exit_rule, index=0)
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

            if remove_exit_group_second_condition:
                updated_exit_rule = _remove_group_condition(existing_exit_rule, index=1)
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

            if remove_entry_window_wrapper:
                updated_entry_rule = _remove_window_wrapper(existing_entry_rule)
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

            if remove_exit_window_wrapper:
                updated_exit_rule = _remove_window_wrapper(existing_exit_rule)
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

            if remove_entry_sequence_first_step:
                updated_entry_rule = _remove_sequence_step(existing_entry_rule, index=0)
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

            if remove_entry_sequence_second_step:
                updated_entry_rule = _remove_sequence_step(existing_entry_rule, index=1)
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

            if remove_exit_sequence_first_step:
                updated_exit_rule = _remove_sequence_step(existing_exit_rule, index=0)
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

            if remove_exit_sequence_second_step:
                updated_exit_rule = _remove_sequence_step(existing_exit_rule, index=1)
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

        if has_position_management_edit:
            if position_management_removed:
                default_config["position_management"] = None
            else:
                default_config["position_management"] = _build_position_management(
                    existing=default_config.get("position_management") or None,
                    scale_in_fraction=scale_in_fraction_edit,
                    scale_out_fraction=scale_out_fraction_edit,
                    profit_reduce_threshold=profit_reduce_threshold_edit,
                )

        if core_overlay_disabled:
            default_config["core_overlay"] = {
                "enabled": False,
                "core_allocation_pct": 0.0,
            }
        elif core_overlay_enabled:
            core_overlay = dict(default_config.get("core_overlay") or {})
            core_overlay["enabled"] = True
            if core_allocation_pct is not None:
                core_overlay["core_allocation_pct"] = core_allocation_pct
            elif core_overlay.get("core_allocation_pct", 0.0) == 0.0:
                core_overlay["core_allocation_pct"] = 0.60
                assumptions.append("Used 60.0% core allocation by default.")
            default_config["core_overlay"] = core_overlay

        risk = dict(default_config.get("risk", {}))

        if partial_take_profit_removed:
            risk["partial_take_profit"] = None
        elif partial_take_profit is not None:
            risk["partial_take_profit"] = partial_take_profit

        if stop_loss_removed:
            risk["stop_loss_pct"] = None
        elif stop_loss_pct is not None:
            risk["stop_loss_pct"] = stop_loss_pct

        if take_profit_removed:
            risk["take_profit_pct"] = None
        elif take_profit_pct is not None:
            risk["take_profit_pct"] = take_profit_pct

        if cooldown_removed:
            risk["cooldown_bars"] = 0
        elif cooldown_edit is not None or "cooldown" in prompt_lower:
            risk["cooldown_bars"] = cooldown_bars
        default_config["risk"] = risk

        if (
            default_config.get("tradable_symbol") != base_config.get("tradable_symbol")
            or default_config.get("entry_rule") != base_config.get("entry_rule")
            or default_config.get("exit_rule") != base_config.get("exit_rule")
        ):
            default_config["name"] = _build_strategy_name(
                default_config["tradable_symbol"],
                default_config["entry_rule"],
                default_config["exit_rule"],
            )
        else:
            default_config["name"] = base_config.get(
                "name",
                _build_strategy_name(
                    default_config["tradable_symbol"],
                    default_config["entry_rule"],
                    default_config["exit_rule"],
                ),
            )

    config = _merge_dict(base_config, default_config)

    effective_symbol = config.get("tradable_symbol", tradable_symbol)
    effective_entry = config.get("entry_rule", entry_rule)
    effective_exit = config.get("exit_rule", exit_rule)
    effective_benchmark = config.get("benchmark_symbol", benchmark_symbol)

    summary_start_date = (
        config.get("start_date", start_date.isoformat())
        if has_current_config
        else start_date.isoformat()
    )
    summary_end_date = (
        config.get("end_date", end_date.isoformat())
        if has_current_config
        else end_date.isoformat()
    )

    summary_parts = [
        _build_summary_intro(
            symbol=effective_symbol,
            start_date_str=summary_start_date,
            end_date_str=summary_end_date,
            assumptions=assumptions,
        ),
        f"with entry rule {_rule_label(effective_entry)}",
        f"and exit rule {_rule_label(effective_exit)}.",
    ]

    if effective_benchmark != effective_symbol:
        summary_parts.append(f"Benchmark set to {effective_benchmark}.")

    if benchmark_symbol != tradable_symbol:
        summary_parts.append(f"Benchmark set to {benchmark_symbol}.")

    if allocation_edit_value is not None and config.get("allocation", {}).get("entry_value") != 1.0:
        summary_parts.append(
            f"Position sizing set to {config['allocation']['entry_value'] * 100:.1f}% of equity."
        )

    if stop_loss_removed:
        summary_parts.append("Stop loss removed.")
    elif stop_loss_pct is not None:
        summary_parts.append(f"Stop loss set to {stop_loss_pct * 100:.1f}%.")

    if take_profit_removed:
        summary_parts.append("Take profit removed.")
    elif take_profit_pct is not None:
        summary_parts.append(f"Take profit set to {take_profit_pct * 100:.1f}%.")

    if cooldown_removed:
        summary_parts.append("Cooldown removed.")
    elif cooldown_edit is not None and cooldown_bars:
        summary_parts.append(f"Cooldown set to {cooldown_bars} bars.")

    if partial_take_profit_removed:
        summary_parts.append("Partial take profit removed.")
    elif partial_take_profit is not None:
        summary_parts.append(
            "Partial take profit set "
            f"at {partial_take_profit['trigger_profit_pct'] * 100:.1f}%, "
            f"sell {partial_take_profit['sell_fraction_of_position'] * 100:.1f}%, "
            f"max {partial_take_profit['max_triggers']} times."
        )

    if position_management_removed:
        summary_parts.append("Position management removed.")
    elif has_position_management_edit:
        summary_parts.append("Position management updated.")

    if core_overlay_disabled:
        summary_parts.append("Core allocation disabled.")
    elif core_overlay_enabled:
        summary_parts.append(
            f"Core allocation set to {config['core_overlay']['core_allocation_pct'] * 100:.1f}%."
        )

    validated = StrategyV2.model_validate(config)
    validated_config = validated.model_dump(mode="json", exclude_none=True)
    changes = _summarize_changes(base_config, validated_config)

    return (
        validated_config,
        " ".join(summary_parts),
        warnings,
        assumptions,
        changes,
    )


def generate_strategy_builder_draft(
    req: StrategyBuilderGenerateRequest,
    *,
    max_backtest_years: int = 5,
) -> tuple[dict, str, list[str], list[str], list[str]]:
    return _generate_strategy_draft(
        req,
        max_backtest_years=max_backtest_years,
    )


def generate_strategy_builder_response(
    req: StrategyBuilderGenerateRequest,
    *,
    max_backtest_years: int = 5,
) -> dict[str, Any]:
    prompt = req.prompt.strip()
    has_current_config = _has_current_config(req)

    if _looks_like_question(prompt):
        answer_message, answer_data = _build_answer_message(
            prompt=prompt,
            max_backtest_years=max_backtest_years,
        )
        return _build_response(
            response_type=StrategyBuilderResponseType.ANSWER,
            message=answer_message,
            answer_data=answer_data,
            guidance_data=(
                _build_guidance_data(
                    guidance_type=StrategyBuilderGuidanceType.NO_CHANGE,
                )
                if has_current_config
                else None
            ),
        )

    try:
        config, summary, warnings, assumptions, changes = generate_strategy_builder_draft(
            req,
            max_backtest_years=max_backtest_years,
        )
    except ValueError as exc:
        message = str(exc)
        return _build_response(
            response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
            message=message,
            validation_data=build_validation_data(
                message=message,
                max_backtest_years=max_backtest_years,
            ),
        )

    if has_current_config and _has_date_edit_intent(prompt) and not changes:
        message = (
            "I could not apply that date change. Please use ISO format like 2021-04-14, "
            "and make sure the new range stays within supported ETF data coverage and your current plan limit."
        )
        return _build_response(
            response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
            message=message,
            validation_data=build_validation_data(
                message=message,
                max_backtest_years=max_backtest_years,
            ),
        )

    if has_current_config and req.context and req.context.current_config == config:
        if _looks_like_edit_request(prompt) and not _is_supported_edit_request(prompt):
            message = UNSUPPORTED_EDIT_MESSAGE
            return _build_response(
                response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
                message=message,
                validation_data=build_validation_data(
                    message=message,
                    max_backtest_years=max_backtest_years,
                ),
                guidance_data=_build_guidance_data(
                    guidance_type=StrategyBuilderGuidanceType.UNSUPPORTED_EDIT_TARGET,
                ),
            )

        return _build_response(
            response_type=StrategyBuilderResponseType.ANSWER,
            message=NO_CHANGE_MESSAGE,
            guidance_data=_build_guidance_data(
                guidance_type=StrategyBuilderGuidanceType.NO_CHANGE,
            ),
        )

    response_type = (
        StrategyBuilderResponseType.UPDATE_DRAFT
        if has_current_config
        else StrategyBuilderResponseType.CREATE_DRAFT
    )

    return _build_response(
        response_type=response_type,
        message=summary,
        config=config,
        summary=summary,
        warnings=warnings,
        assumptions=assumptions,
        changes=changes,
    )