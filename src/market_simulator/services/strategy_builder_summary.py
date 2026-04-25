from __future__ import annotations

from typing import Any

_RELATIVE_STRENGTH_RULE_TYPES = {
    "relative_return_above",
    "relative_strength_above",
    "relative_strength_below",
}
_RSI_RULE_TYPES = {"rsi_below", "rsi_above"}


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


def _is_structural_rule_change(before: dict | None, after: dict | None) -> bool:
    if not before and not after:
        return False
    if not isinstance(before, dict) or not isinstance(after, dict):
        return before != after

    return (
        before.get("kind") != after.get("kind")
        or _rule_label(before) != _rule_label(after)
    )


def _format_enabled(value: Any) -> str:
    return "enabled" if bool(value) else "disabled"


def _format_pct(value: Any) -> str:
    if value is None:
        return "none"
    return f"{float(value) * 100:.1f}%"


def _format_number(value: Any) -> str:
    if value is None:
        return "none"
    return f"{float(value):g}"


def _format_month_values(value: Any) -> str:
    if not value:
        return "none"
    return ", ".join(str(month) for month in value)


def _record_change(changes: list[str], before: Any, after: Any, label: str, formatter=str) -> None:
    if before == after:
        return
    changes.append(f"Updated {label} from {formatter(before)} to {formatter(after)}.")


def _rule_type(rule: dict[str, Any]) -> str | None:
    rule_type = rule.get("type")
    return rule_type if isinstance(rule_type, str) else None


def _is_relative_strength_rule(rule: dict[str, Any]) -> bool:
    return _rule_type(rule) in _RELATIVE_STRENGTH_RULE_TYPES


def _record_threshold_change(
    changes: list[str],
    base_rule: dict[str, Any],
    final_rule: dict[str, Any],
    side: str,
) -> None:
    rule_type = _rule_type(final_rule) or _rule_type(base_rule)
    if rule_type in _RSI_RULE_TYPES:
        label = f"RSI {side} threshold"
        formatter = _format_number
    elif rule_type in _RELATIVE_STRENGTH_RULE_TYPES:
        label = "relative strength threshold" if side == "entry" else "relative strength exit threshold"
        formatter = _format_pct
    else:
        label = f"{side} threshold"
        formatter = str

    _record_change(
        changes,
        base_rule.get("threshold"),
        final_rule.get("threshold"),
        label,
        formatter,
    )


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
        base_config.get("transaction_cost_bps"),
        config.get("transaction_cost_bps"),
        "transaction cost",
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
        base_allocation.get("max_position_pct"),
        final_allocation.get("max_position_pct"),
        "max position",
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
    _record_threshold_change(changes, base_entry, final_entry, "entry")
    _record_threshold_change(changes, base_exit, final_exit, "exit")
    if _is_structural_rule_change(base_entry, final_entry):
        _record_change(
            changes,
            _rule_label(base_entry),
            _rule_label(final_entry),
            "entry rule",
        )

    if _is_structural_rule_change(base_exit, final_exit):
        _record_change(
            changes,
            _rule_label(base_exit),
            _rule_label(final_exit),
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
    if _is_relative_strength_rule(base_entry) or _is_relative_strength_rule(final_entry):
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


def _build_strategy_summary(
    *,
    config: dict[str, Any],
    tradable_symbol: str,
    benchmark_symbol: str,
    start_date,
    end_date,
    has_current_config: bool,
    assumptions: list[str],
    transaction_cost_bps_edit: float | None,
    allocation_edit_value: float | None,
    max_position_pct_edit: float | None,
    stop_loss_removed: bool,
    stop_loss_pct: float | None,
    take_profit_removed: bool,
    take_profit_pct: float | None,
    cooldown_removed: bool,
    cooldown_edit: int | None,
    cooldown_bars: int,
    partial_take_profit_removed: bool,
    partial_take_profit: dict[str, Any] | None,
    position_management_removed: bool,
    has_position_management_edit: bool,
    core_overlay_disabled: bool,
    core_overlay_enabled: bool,
) -> str:
    effective_symbol = config.get("tradable_symbol", tradable_symbol)
    effective_entry = config.get("entry_rule")
    effective_exit = config.get("exit_rule")
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

    if transaction_cost_bps_edit is not None:
        summary_parts.append(f"Transaction cost set to {transaction_cost_bps_edit:.1f} bps.")

    if allocation_edit_value is not None and config.get("allocation", {}).get("entry_value") != 1.0:
        summary_parts.append(
            f"Position sizing set to {config['allocation']['entry_value'] * 100:.1f}% of equity."
        )

    if max_position_pct_edit is not None:
        summary_parts.append(
            f"Max position set to {config['allocation']['max_position_pct'] * 100:.1f}%."
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

    return " ".join(summary_parts)


__all__ = [
    "_build_strategy_name",
    "_build_strategy_summary",
    "_rule_label",
    "_summarize_changes",
]
