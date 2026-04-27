from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from market_simulator.services.etf_metadata_service import get_etf_history_range
from market_simulator.settings import get_settings


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
        r"\b(entry|exit)\s+threshold\b",
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
        r"\b(entry|exit)\s+not\s+inner\s+rule\b",
        r"\b(remove|delete)\s+(entry|exit)\s+not\s+wrapper\b",
        r"\b(remove|delete)\s+(first|second)\s+step\s+of\s+(entry|exit)\s+sequence\b",
        r"\bpartial\s+take\s+profit\b",
        r"\bscale\s+in\b",
        r"\bscale\s+out\b",
        r"\bprofit\s+reduce\s+threshold\b",
        r"\bposition\s+management\b",
        r"\bcore\s+allocation\b",
        r"\bcore\s+overlay\b",
        r"\bmax\s+position\b",
        r"\bmax\s+position\s+pct\b",
        r"\btransaction\s+cost\b",
        r"\bbps\b",
        r"\bfee\b",
        r"\bfees\b",
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


def _extract_initial_capital(text: str) -> tuple[float, list[str]]:
    assumptions: list[str] = []

    patterns = [
        r"(?:initial\s+capital|capital|starting\s+with|start\s+with)\s*\$?(\d[\d,]*(?:\.\d+)?)",
        r"\$(\d[\d,]*(?:\.\d+)?)\s+(?:initial\s+capital|capital)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value_text = match.group(1).replace(",", "")
            if value_text:
                return float(value_text), assumptions

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
        r"(?:change|set|update)\s+(?:the\s+)?entry\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"entry\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"change\s+rsi\s+entry\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+rsi\s+entry\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"update\s+rsi\s+entry\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"rsi\s+entry\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"change\s+entry\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+entry\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"update\s+entry\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"entry\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"change\s+rsi\s+entry\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+rsi\s+entry\s+to\s+(\d+(?:\.\d+)?)",
        r"update\s+rsi\s+entry\s+to\s+(\d+(?:\.\d+)?)",
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
        r"(?:change|set|update)\s+(?:the\s+)?exit\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"exit\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"change\s+rsi\s+exit\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+rsi\s+exit\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"update\s+rsi\s+exit\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"rsi\s+exit\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"change\s+exit\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+exit\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"update\s+exit\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"exit\s+rsi\s+threshold\s+to\s+(\d+(?:\.\d+)?)",
        r"change\s+rsi\s+exit\s+to\s+(\d+(?:\.\d+)?)",
        r"set\s+rsi\s+exit\s+to\s+(\d+(?:\.\d+)?)",
        r"update\s+rsi\s+exit\s+to\s+(\d+(?:\.\d+)?)",
        r"rsi\s+exit\s+to\s+(\d+(?:\.\d+)?)",
        r"exit\s+rsi\s+to\s+(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_rsi_entry_lookback_edit(text: str) -> int | None:
    patterns = [
        r"change\s+rsi\s+entry\s+lookback\s+to\s+(\d+)",
        r"set\s+rsi\s+entry\s+lookback\s+to\s+(\d+)",
        r"rsi\s+entry\s+lookback\s+to\s+(\d+)",
        r"change\s+entry\s+rsi\s+lookback\s+to\s+(\d+)",
        r"set\s+entry\s+rsi\s+lookback\s+to\s+(\d+)",
        r"entry\s+rsi\s+lookback\s+to\s+(\d+)",
    ]
    return _extract_int(text, patterns)


def _extract_rsi_exit_lookback_edit(text: str) -> int | None:
    patterns = [
        r"change\s+rsi\s+exit\s+lookback\s+to\s+(\d+)",
        r"set\s+rsi\s+exit\s+lookback\s+to\s+(\d+)",
        r"rsi\s+exit\s+lookback\s+to\s+(\d+)",
        r"change\s+exit\s+rsi\s+lookback\s+to\s+(\d+)",
        r"set\s+exit\s+rsi\s+lookback\s+to\s+(\d+)",
        r"exit\s+rsi\s+lookback\s+to\s+(\d+)",
    ]
    return _extract_int(text, patterns)


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


def _extract_sma_above_pair(text: str) -> tuple[int, int] | None:
    patterns = [
        r"(\d+)\s*(?:day|d)?\s*sma\s+(?:is\s+)?above\s+(\d+)\s*(?:day|d)?\s*sma",
        r"sma\s+above\s+(\d+)\s*/\s*(\d+)",
        r"(\d+)\s*/\s*(\d+)\s*sma\s+above",
        r"(\d+)\s*(?:day|d)?\s+sma\s+above\s+(\d+)\s*(?:day|d)?\s+sma",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            fast_window = int(match.group(1))
            slow_window = int(match.group(2))
            if fast_window != slow_window:
                return fast_window, slow_window
    return None


def _has_sma_above_state_intent(text: str) -> bool:
    text_lower = text.lower()

    if "cross above" in text_lower or "crosses above" in text_lower or "crossing above" in text_lower:
        return False

    return bool(
        re.search(
            r"\bsma\s+above\b|\bis\s+above\b",
            text_lower,
        )
    )


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


def _extract_seasonality_month_edit_action(text: str) -> str | None:
    if re.search(
        r"\b(add|include)\b.*\b(seasonality|months?|month values)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return "add"

    if re.search(
        r"\b(remove|delete|drop)\b.*\b(seasonality|months?|month values)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return "remove"

    if re.search(
        r"\b(change|set|update)\b.*\b(seasonality|months?|month values)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return "set"

    return None


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
        above_pair = _extract_sma_above_pair(clause_text)
        pair = above_pair if above_pair is not None else _extract_sma_pair_any_direction(clause_text)
        fast_window, slow_window = pair if pair else (20, 50)

        if pair is None:
            assumptions.append("Used default moving-average windows 20/50 inside a combined rule clause.")

        if _has_sma_above_state_intent(clause_text):
            rule_type = "sma_above"
        elif "below" in clause_lower:
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


def _extract_not_inner_rule_edit(
    text: str,
    *,
    side: str,
) -> str | None:
    patterns = [
        rf"change\s+{side}\s+not\s+inner\s+rule\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"set\s+{side}\s+not\s+inner\s+rule\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
        rf"{side}\s+not\s+inner\s+rule\s+to\s+(.+?)(?:\s+and\s+change\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ,.")
    return None


def _has_remove_not_wrapper_intent(
    text: str,
    *,
    side: str,
) -> bool:
    return bool(
        re.search(
            rf"(?:remove|delete)\s+{side}\s+not\s+wrapper",
            text,
            flags=re.IGNORECASE,
        )
    )


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


def _extract_max_position_pct_edit(text: str) -> float | None:
    patterns = [
        r"change\s+max\s+position(?:\s+pct)?\s+to\s+(\d+(?:\.\d+)?)%",
        r"set\s+max\s+position(?:\s+pct)?\s+to\s+(\d+(?:\.\d+)?)%",
        r"max\s+position(?:\s+pct)?\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1)) / 100.0
            return min(max(value, 0.01), 1.0)
    return None


def _extract_transaction_cost_bps_edit(text: str) -> float | None:
    patterns = [
        r"change\s+transaction\s+cost\s+to\s+(\d+(?:\.\d+)?)\s*bps?",
        r"set\s+transaction\s+cost\s+to\s+(\d+(?:\.\d+)?)\s*bps?",
        r"transaction\s+cost\s+(?:at|to)\s+(\d+(?:\.\d+)?)\s*bps?",
        r"change\s+fees?\s+to\s+(\d+(?:\.\d+)?)\s*bps?",
        r"set\s+fees?\s+to\s+(\d+(?:\.\d+)?)\s*bps?",
        r"fees?\s+(?:at|to)\s+(\d+(?:\.\d+)?)\s*bps?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
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
            r"core\s+allocation\s+(\d+(?:\.\d+)?)%",
            r"core\s+allocation\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
            r"enable\s+core\s+allocation\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
            r"core\s+overlay\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
            r"(\d+(?:\.\d+)?)%\s+core\b",
            r"(\d+(?:\.\d+)?)%\s+always[-\s]+invested\s+core\s+allocation\b",
        ],
    )


def _extract_overlay_allocation_pct(text: str) -> float | None:
    return _extract_percent(
        text,
        [
            r"overlay\s+allocation\s+(\d+(?:\.\d+)?)%",
            r"overlay\s+allocation\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
            r"remaining\s+(\d+(?:\.\d+)?)%\s+(?:as\s+(?:a\s+)?)?(?:tactical\s+)?overlay\b",
            r"(\d+(?:\.\d+)?)%\s+overlay\b",
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
            r"core[-\s]+overlay\s+(?:enabled|strategy)|enable\s+core\s+(?:allocation|overlay)|core\s+(?:allocation|overlay)\s+(?:(?:at|to)\s+)?\d+(?:\.\d+)?%|\d+(?:\.\d+)?%\s+core\b|\d+(?:\.\d+)?%\s+always[-\s]+invested\s+core\s+allocation\b|overlay\s+allocation\s+(?:(?:at|to)\s+)?\d+(?:\.\d+)?%|remaining\s+\d+(?:\.\d+)?%\s+(?:as\s+(?:a\s+)?)?(?:tactical\s+)?overlay\b|\d+(?:\.\d+)?%\s+overlay\b",
            text,
            flags=re.IGNORECASE,
        )
    )



__all__ = [
    "_build_atomic_rule_from_clause",
    "_build_confirmation_rules",
    "_build_default_date_range",
    "_build_fallback_default_date_range",
    "_build_position_management",
    "_build_rule_from_clause",
    "_extract_allocation_value",
    "_extract_allocation_value_edit",
    "_extract_benchmark_symbol",
    "_extract_confirmation_family",
    "_extract_cooldown_edit",
    "_extract_core_allocation_pct",
    "_extract_date_range",
    "_extract_entry_exit_rule_clauses",
    "_extract_entry_fast_window_edit",
    "_extract_entry_slow_window_edit",
    "_extract_explicit_date_edits",
    "_extract_group_condition_edit",
    "_extract_group_operator_edit",
    "_extract_initial_capital",
    "_extract_int",
    "_extract_max_position_pct_edit",
    "_extract_month_values",
    "_extract_not_inner_rule_edit",
    "_extract_overlay_allocation_pct",
    "_extract_partial_take_profit",
    "_extract_percent",
    "_extract_primary_symbol",
    "_extract_profit_reduce_threshold_edit",
    "_extract_reference_symbols",
    "_extract_relative_strength_lookback_edit",
    "_extract_relative_strength_reference_symbol_edit",
    "_extract_relative_strength_rules",
    "_extract_relative_strength_threshold_edit",
    "_extract_rsi_entry_lookback_edit",
    "_extract_rsi_entry_threshold_edit",
    "_extract_rsi_exit_lookback_edit",
    "_extract_rsi_exit_threshold_edit",
    "_extract_rsi_rule",
    "_extract_scale_in_fraction_edit",
    "_extract_scale_out_fraction_edit",
    "_extract_seasonality_month_edit_action",
    "_extract_sequence_rule_clause",
    "_extract_sequence_step_edit",
    "_extract_sma_above_pair",
    "_extract_sma_crossover_pair",
    "_extract_sma_pair_any_direction",
    "_extract_symbols",
    "_extract_temporal_bars_edit",
    "_extract_temporal_mode_edit",
    "_extract_tradable_symbol_edit",
    "_extract_transaction_cost_bps_edit",
    "_extract_window_inner_rule_edit",
    "_extract_window_rule_clause",
    "_extract_exit_fast_window_edit",
    "_extract_exit_slow_window_edit",
    "_has_benchmark_edit_intent",
    "_has_confirmation_add_intent",
    "_has_confirmation_remove_intent",
    "_has_core_overlay_disable",
    "_has_core_overlay_enable",
    "_has_cooldown_removal",
    "_has_date_edit_intent",
    "_has_nested_composite_edit",
    "_has_partial_relative_strength_edit",
    "_has_partial_sma_window_edit",
    "_has_partial_take_profit_removal",
    "_has_position_management_removal",
    "_has_remove_group_condition_intent",
    "_has_remove_not_wrapper_intent",
    "_has_remove_sequence_step_intent",
    "_has_remove_window_wrapper_intent",
    "_has_sma_above_state_intent",
    "_has_stop_loss_removal",
    "_has_take_profit_removal",
    "_has_temporal_rule_edit",
    "_is_supported_edit_request",
    "_looks_like_edit_request",
    "_looks_like_question",
    "_split_clause_conditions",
    "_MONTH_NAME_TO_NUMBER",
]
