from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from market_simulator.api.deps import get_current_user
from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderGenerateRequest,
    StrategyBuilderGenerateResponse,
)
from market_simulator.models.strategy_v2 import StrategyV2

router = APIRouter(prefix="/strategy-builder", tags=["strategy-builder"])

SUPPORTED_SYMBOLS = {
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "VTI",
    "GLD",
    "SLV",
    "TLT",
    "IEF",
    "HYG",
    "LQD",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "XLRE",
    "ARKK",
    "VUG",
    "VTV",
    "QUAL",
    "MTUM",
    "IBIT",
}


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


def _extract_date_range(text: str) -> tuple[date, date, list[str]]:
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

    assumptions.append("Used the default backtest range 2018-01-02 to 2024-12-31.")
    return date(2018, 1, 2), date(2024, 12, 31), assumptions


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


def _build_strategy_name(
    symbol: str,
    entry_rule: dict,
    exit_rule: dict,
) -> str:
    entry_label = entry_rule["type"].replace("_", "-")
    exit_label = exit_rule["type"].replace("_", "-")
    return f"{symbol.lower()}-{entry_label}-to-{exit_label}"


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
        r"allocation\s+(?:at|to)\s+(\d+(?:\.\d+)?)%",
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


def _format_pct(value: Any) -> str:
    if value is None:
        return "none"
    return f"{float(value) * 100:.1f}%"


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

    return changes


def _generate_strategy_draft(
    req: StrategyBuilderGenerateRequest,
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

    start_date, end_date, date_assumptions = _extract_date_range(prompt)
    assumptions.extend(date_assumptions)

    initial_capital, capital_assumptions = _extract_initial_capital(prompt)
    assumptions.extend(capital_assumptions)

    allocation_edit_value = _extract_allocation_value_edit(prompt)
    allocation_value, allocation_assumptions = _extract_allocation_value(prompt)
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
            r"take\s+profit\s+(?:at\s+|to\s+)?(\d+(?:\.\d+)?)%",
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

    entry_rule = None
    exit_rule = None

    rsi_buy = _extract_rsi_rule(prompt, direction="below")
    rsi_sell = _extract_rsi_rule(prompt, direction="above")
    rsi_entry_threshold_edit = _extract_rsi_entry_threshold_edit(prompt)
    rsi_exit_threshold_edit = _extract_rsi_exit_threshold_edit(prompt)
    sma_pair = _extract_sma_crossover_pair(prompt)

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

    if entry_rule is None:
        entry_rule = {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 30,
        }
        warnings.append("Entry rule defaulted to RSI(14) below 30.")

    if exit_rule is None:
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
        default_config["risk"] = {
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "partial_take_profit": None,
            "cooldown_bars": cooldown_bars,
        }
        default_config["core_overlay"] = {
            "enabled": False,
            "core_allocation_pct": 0.0,
        }
        default_config["position_management"] = None
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

        risk = dict(default_config.get("risk", {}))
        risk.setdefault("cooldown_bars", 0)
        default_config["risk"] = risk

        if any(phrase in prompt_lower for phrase in ["benchmark", "as benchmark", "set benchmark", "benchmark is", "change benchmark"]):
            default_config["benchmark_symbol"] = benchmark_symbol

        if re.search(r"(?:capital|start with|\$)", prompt_lower):
            default_config["initial_capital"] = initial_capital

        if allocation_edit_value is not None or re.search(r"%\s+of\s+equity|allocation|allocate", prompt_lower):
            allocation = dict(default_config.get("allocation", {}))
            allocation["entry_mode"] = "percent_of_equity"
            allocation["entry_value"] = allocation_edit_value if allocation_edit_value is not None else allocation_value
            allocation.setdefault("max_position_pct", 1.0)
            default_config["allocation"] = allocation

        existing_entry_rule = dict(default_config.get("entry_rule", {}))
        existing_exit_rule = dict(default_config.get("exit_rule", {}))

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

        elif entry_rule is not None and (
            "rsi" in prompt_lower
            or "mean reversion" in prompt_lower
            or "moving average" in prompt_lower
            or "sma" in prompt_lower
            or "entry" in prompt_lower
            or "buy" in prompt_lower
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

        elif exit_rule is not None and (
            "rsi" in prompt_lower
            or "mean reversion" in prompt_lower
            or "moving average" in prompt_lower
            or "sma" in prompt_lower
            or "exit" in prompt_lower
            or "sell" in prompt_lower
        ):
            default_config["exit_rule"] = exit_rule

        risk = dict(default_config.get("risk", {}))
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

        default_config["name"] = _build_strategy_name(
            default_config["tradable_symbol"],
            default_config["entry_rule"],
            default_config["exit_rule"],
        )

    config = _merge_dict(base_config, default_config)

    effective_symbol = config.get("tradable_symbol", tradable_symbol)
    effective_entry = config.get("entry_rule", entry_rule)
    effective_exit = config.get("exit_rule", exit_rule)
    effective_benchmark = config.get("benchmark_symbol", benchmark_symbol)

    summary_parts = [
        f"Drafted a strategy for {effective_symbol}",
        f"from {config.get('start_date', start_date.isoformat()) if has_current_config else start_date.isoformat()}",
        f"to {config.get('end_date', end_date.isoformat()) if has_current_config else end_date.isoformat()}",
        f"with entry rule {effective_entry['type']}",
        f"and exit rule {effective_exit['type']}.",
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


@router.post("/generate", response_model=StrategyBuilderGenerateResponse)
def generate_strategy_draft_api(
    req: StrategyBuilderGenerateRequest,
    user=Depends(get_current_user),
):
    _ = user

    config, summary, warnings, assumptions, changes = _generate_strategy_draft(req)

    return StrategyBuilderGenerateResponse(
        config=config,
        summary=summary,
        warnings=warnings,
        assumptions=assumptions,
        changes=changes,
    )
