from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderAnswerType,
    StrategyBuilderGenerateRequest,
    StrategyBuilderGuidanceType,
    StrategyBuilderResponseType,
)
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.parameter_sweep import (
    DEFAULT_MAX_VARIANTS,
    ParameterSweepError,
    build_sweep_request,
    get_nested,
    normalize_ranking_metric,
    variant_count,
)
from market_simulator.services.strategy_builder_capabilities import (
    NO_CHANGE_MESSAGE,
    UNSUPPORTED_EDIT_MESSAGE,
)
from market_simulator.services.strategy_builder_rule_tree import (
    _add_confirmation_rule,
    _has_confirmation_rule,
    _has_moving_average_rule,
    _has_month_in_rule,
    _has_not_rule_anywhere,
    _has_relative_strength_rule,
    _has_rsi_rule,
    _remove_confirmation_rule,
    _remove_first_group_condition,
    _remove_first_not_wrapper,
    _remove_first_sequence_step,
    _remove_first_window_wrapper,
    _rewrite_rule_tradable_symbol,
    _sync_reference_symbols,
    _try_add_confirmation_rule_recursively,
    _update_first_group_condition,
    _update_first_group_operator,
    _update_first_not_inner_rule,
    _update_first_sequence_bars,
    _update_first_sequence_step,
    _update_first_window_bars,
    _update_first_window_inner_rule,
    _update_first_window_mode,
    _update_month_in_rules,
    _update_moving_average_rules,
    _update_relative_strength_rules,
    _update_rsi_rules,
)
from market_simulator.services.strategy_builder_summary import (
    _build_strategy_name,
    _build_strategy_summary,
    _rule_label,
    _summarize_changes,
)
from market_simulator.services.strategy_builder_response import (
    _build_answer_message,
    _build_guidance_data,
    _build_response,
    build_validation_data,
)
from market_simulator.services.strategy_builder_config import (
    _build_create_flow_default_config,
    _build_update_flow_default_config,
    _merge_dict,
)
from market_simulator.services.strategy_builder_parsers import (
    _build_confirmation_rules,
    _build_position_management,
    _build_rule_from_clause,
    _extract_allocation_value,
    _extract_allocation_value_edit,
    _extract_benchmark_symbol,
    _extract_confirmation_family,
    _extract_cooldown_edit,
    _extract_core_allocation_pct,
    _extract_date_range,
    _extract_entry_exit_rule_clauses,
    _extract_entry_fast_window_edit,
    _extract_entry_rule_clause,
    _extract_entry_slow_window_edit,
    _extract_exit_fast_window_edit,
    _extract_exit_rule_clause,
    _extract_exit_slow_window_edit,
    _extract_explicit_date_edits,
    _extract_group_condition_edit,
    _extract_group_operator_edit,
    _extract_initial_capital,
    _extract_max_position_pct_edit,
    _extract_month_values,
    _extract_not_inner_rule_edit,
    _extract_overlay_allocation_pct,
    _extract_partial_take_profit,
    _extract_percent,
    _extract_primary_symbol,
    _extract_profit_reduce_threshold_edit,
    _extract_reference_symbols,
    _extract_realized_volatility_rule,
    _extract_relative_strength_lookback_edit,
    _extract_relative_strength_reference_symbol_edit,
    _extract_relative_strength_rules,
    _extract_relative_strength_threshold_edit,
    _extract_rsi_entry_lookback_edit,
    _extract_rsi_entry_threshold_edit,
    _extract_rsi_exit_lookback_edit,
    _extract_rsi_exit_threshold_edit,
    _extract_rsi_rule,
    _extract_scale_in_fraction_edit,
    _extract_scale_out_fraction_edit,
    _extract_seasonality_month_edit_action,
    _extract_sequence_step_edit,
    _extract_sma_above_pair,
    _extract_sma_crossover_pair,
    _extract_sma_filter_window_edit,
    _extract_single_sma_window,
    _extract_temporal_bars_edit,
    _extract_temporal_mode_edit,
    _extract_tradable_symbol_edit,
    _extract_transaction_cost_bps_edit,
    _extract_window_inner_rule_edit,
    _has_benchmark_edit_intent,
    _has_confirmation_add_intent,
    _has_confirmation_remove_intent,
    _has_core_overlay_disable,
    _has_core_overlay_enable,
    _has_cooldown_removal,
    _has_date_edit_intent,
    _has_nested_composite_edit,
    _has_partial_relative_strength_edit,
    _has_partial_sma_window_edit,
    _has_partial_take_profit_removal,
    _has_position_management_removal,
    _has_remove_group_condition_intent,
    _has_remove_not_wrapper_intent,
    _has_remove_sequence_step_intent,
    _has_remove_window_wrapper_intent,
    _has_sma_above_state_intent,
    _has_stop_loss_removal,
    _has_take_profit_removal,
    _has_temporal_rule_edit,
    _looks_like_reference_series_filter_intent,
    _is_supported_edit_request,
    _looks_like_edit_request,
    _looks_like_question,
)


def _has_current_config(req: StrategyBuilderGenerateRequest) -> bool:
    current_config = req.context.current_config if req.context else None
    return isinstance(current_config, dict) and bool(current_config)


def _has_price_above_sma_intent(prompt: str) -> bool:
    return bool(re.search(r"\b(above|over)\b", prompt, flags=re.IGNORECASE))


def _has_price_below_sma_intent(prompt: str) -> bool:
    return bool(
        re.search(
            r"\b(below|under|falls?\s+below|drops?\s+below)\b",
            prompt,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_exit_only_prompt(prompt: str) -> bool:
    has_exit = bool(re.search(r"\b(exit|sell|selling)\b", prompt, flags=re.IGNORECASE))
    has_entry = bool(re.search(r"\b(entry|buy|buying)\b", prompt, flags=re.IGNORECASE))
    return has_exit and not has_entry


def _looks_like_entry_only_prompt(prompt: str) -> bool:
    has_entry = bool(re.search(r"\b(entry|buy|buying)\b", prompt, flags=re.IGNORECASE))
    has_exit = bool(re.search(r"\b(exit|sell|selling)\b", prompt, flags=re.IGNORECASE))
    return has_entry and not has_exit


def _has_numeric_threshold(rule: dict[str, Any]) -> bool:
    threshold = rule.get("threshold")
    return isinstance(threshold, (int, float)) and not isinstance(threshold, bool)


def _should_attach_question_guidance(
    *,
    prompt: str,
    has_current_config: bool,
    answer_type: StrategyBuilderAnswerType | str | None,
) -> bool:
    if not has_current_config:
        return False

    if answer_type != StrategyBuilderAnswerType.GENERAL:
        return False

    prompt_lower = prompt.lower()
    return (
        "this draft" in prompt_lower
        or "current draft" in prompt_lower
        or "what can this draft do" in prompt_lower
        or "tell me what this draft can do" in prompt_lower
    )


def _requires_existing_draft_context(prompt: str) -> bool:
    text = prompt.strip().lower()

    explicit_context_phrases = (
        "this strategy",
        "this draft",
        "current strategy",
        "current draft",
        "existing strategy",
        "existing draft",
    )
    if any(phrase in text for phrase in explicit_context_phrases):
        return True

    contextual_starters = (
        "change ",
        "set ",
        "update ",
        "remove ",
        "delete ",
        "replace ",
        "switch ",
    )
    if text.startswith(contextual_starters):
        return True

    if text.startswith("add ") and "strategy" not in text:
        return True

    if " instead" in text:
        return True

    return False


_UNSUPPORTED_ALLOCATION_ADJUSTMENT_MESSAGE = (
    "I cannot build that draft faithfully yet. The deterministic builder can use "
    "VIX and rates as entry, exit, filter, or supported add/reduce overlay conditions, "
    "but I need explicit reference-series thresholds to build add/reduce exposure "
    "faithfully. Try a supported version like "
    '"Only trade QQQ when VIX is below 25.", '
    '"Buy QQQ when VIX is below 15 and sell when VIX is above 35.", or '
    '"Buy and hold QQQ. Add when VIX is below 15. Reduce when VIX is above 35."'
)


def _looks_like_unsupported_allocation_adjustment_prompt(prompt: str) -> bool:
    patterns = (
        r"\bbuy\s+and\s+hold\b",
        r"\b(?:add|reduce|trim)\s+when\b",
        r"\b(?:add|reduce|trim)\s+(?:exposure|position|allocation)\s+when\b",
        r"\b(?:increase|decrease)\s+exposure\s+when\b",
    )
    return any(re.search(pattern, prompt, flags=re.IGNORECASE) for pattern in patterns)


_ADD_REDUCE_ACTION_CLAUSE_PATTERN = re.compile(
    r"\b(?P<action>add|increase|reduce|trim|decrease)"
    r"(?:\s+(?:exposure|position|allocation))?\s+when\s+"
    r"(?P<clause>.+?)"
    r"(?=(?:\s*(?:[.;,]\s*|\band\s+)"
    r"(?:add|increase|reduce|trim|decrease)\b)|[.;]|$)",
    flags=re.IGNORECASE,
)


def _is_reference_series_threshold_rule(rule: dict[str, Any] | None) -> bool:
    if not isinstance(rule, dict):
        return False

    threshold = rule.get("threshold")
    return (
        rule.get("kind") == "atomic"
        and rule.get("type") in {"series_below", "series_above"}
        and isinstance(rule.get("symbol"), str)
        and isinstance(threshold, (int, float))
        and not isinstance(threshold, bool)
    )


def _extract_add_reduce_reference_series_setup(
    prompt: str,
    *,
    tradable_symbol: str,
    benchmark_symbol: str,
) -> dict[str, Any] | None:
    add_rule: dict[str, Any] | None = None
    reduce_rule: dict[str, Any] | None = None

    for match in _ADD_REDUCE_ACTION_CLAUSE_PATTERN.finditer(prompt):
        action = match.group("action").lower()
        clause = match.group("clause").strip(" .,")
        try:
            rule, _ = _build_rule_from_clause(
                clause,
                tradable_symbol=tradable_symbol,
                fallback_reference_symbol=benchmark_symbol,
                side="entry" if action in {"add", "increase"} else "exit",
            )
        except ValueError:
            return None
        if not _is_reference_series_threshold_rule(rule):
            return None

        if action in {"add", "increase"}:
            if add_rule is not None:
                return None
            add_rule = rule
        else:
            if reduce_rule is not None:
                return None
            reduce_rule = rule

    if add_rule is None or reduce_rule is None:
        return None

    return {
        "entry_rule": add_rule,
        "exit_rule": reduce_rule,
        "reference_symbols": sorted(
            {
                str(add_rule["symbol"]).upper(),
                str(reduce_rule["symbol"]).upper(),
            }
        ),
    }


def _build_add_reduce_strategy_name(
    *,
    tradable_symbol: str,
    setup: dict[str, Any],
) -> str:
    labels = []
    for symbol in setup.get("reference_symbols", []):
        label = str(symbol).upper()
        if label not in labels:
            labels.append(label)

    reference_label = " + ".join(labels) if labels else "Reference Series"
    return f"{tradable_symbol.upper()} {reference_label} Add Reduce Strategy"


def _resolve_effective_symbols(
    *,
    tradable_symbol: str,
    benchmark_symbol: str,
    current_config: dict[str, Any] | None,
    has_current_config: bool,
) -> tuple[str, str]:
    effective_tradable_symbol = (
        current_config.get("tradable_symbol", tradable_symbol)
        if has_current_config and isinstance(current_config, dict)
        else tradable_symbol
    )
    effective_benchmark_symbol = (
        current_config.get("benchmark_symbol", benchmark_symbol)
        if has_current_config and isinstance(current_config, dict)
        else benchmark_symbol
    )
    return effective_tradable_symbol, effective_benchmark_symbol


def _extract_risk_and_position_inputs(
    *,
    prompt: str,
    assumptions: list[str],
) -> dict[str, Any]:
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
    overlay_allocation_pct = _extract_overlay_allocation_pct(prompt)
    if core_allocation_pct is None and overlay_allocation_pct is not None:
        core_allocation_pct = max(0.0, min(1.0, 1.0 - overlay_allocation_pct))
    core_overlay_disabled = _has_core_overlay_disable(prompt)
    core_overlay_enabled = (
        _has_core_overlay_enable(prompt)
        or core_allocation_pct is not None
        or overlay_allocation_pct is not None
    )

    return {
        "stop_loss_removed": stop_loss_removed,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_removed": take_profit_removed,
        "take_profit_pct": take_profit_pct,
        "cooldown_removed": cooldown_removed,
        "cooldown_edit": cooldown_edit,
        "cooldown_bars": cooldown_bars,
        "partial_take_profit_removed": partial_take_profit_removed,
        "partial_take_profit": partial_take_profit,
        "scale_in_fraction_edit": scale_in_fraction_edit,
        "scale_out_fraction_edit": scale_out_fraction_edit,
        "profit_reduce_threshold_edit": profit_reduce_threshold_edit,
        "position_management_removed": position_management_removed,
        "has_position_management_edit": has_position_management_edit,
        "core_allocation_pct": core_allocation_pct,
        "core_overlay_disabled": core_overlay_disabled,
        "core_overlay_enabled": core_overlay_enabled,
        "overlay_allocation_pct": overlay_allocation_pct,
    }


def _extract_core_prompt_inputs(
    *,
    prompt: str,
    max_backtest_years: int,
    assumptions: list[str],
    has_current_config: bool,
) -> dict[str, Any]:
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
    max_position_pct_edit = _extract_max_position_pct_edit(prompt)
    transaction_cost_bps_edit = _extract_transaction_cost_bps_edit(prompt)
    allocation_value, allocation_assumptions = _extract_allocation_value(prompt)
    explicit_date_edits = _extract_explicit_date_edits(prompt)
    assumptions.extend(allocation_assumptions)

    return {
        "tradable_symbol": tradable_symbol,
        "benchmark_symbol": benchmark_symbol,
        "tradable_symbol_edit": tradable_symbol_edit,
        "reference_symbols": reference_symbols,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "allocation_edit_value": allocation_edit_value,
        "max_position_pct_edit": max_position_pct_edit,
        "transaction_cost_bps_edit": transaction_cost_bps_edit,
        "allocation_value": allocation_value,
        "explicit_date_edits": explicit_date_edits,
    }


def _extract_rule_edit_intents(
    *,
    prompt: str,
) -> dict[str, Any]:
    month_values = _extract_month_values(prompt)

    seasonality_month_edit_action = _extract_seasonality_month_edit_action(prompt)
    has_seasonality_month_edit = False

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
    entry_not_inner_rule_edit = _extract_not_inner_rule_edit(
        prompt,
        side="entry",
    )
    exit_not_inner_rule_edit = _extract_not_inner_rule_edit(
        prompt,
        side="exit",
    )
    has_not_rule_edit_intent = any(
        value is not None
        for value in (
            entry_not_inner_rule_edit,
            exit_not_inner_rule_edit,
        )
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
    remove_entry_not_wrapper = _has_remove_not_wrapper_intent(
        prompt,
        side="entry",
    )
    remove_exit_not_wrapper = _has_remove_not_wrapper_intent(
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
            remove_entry_not_wrapper,
            remove_exit_not_wrapper,
            remove_entry_window_wrapper,
            remove_exit_window_wrapper,
            remove_entry_sequence_first_step,
            remove_entry_sequence_second_step,
            remove_exit_sequence_first_step,
            remove_exit_sequence_second_step,
        )
    )

    return {
        "month_values": month_values,
        "seasonality_month_edit_action": seasonality_month_edit_action,
        "has_seasonality_month_edit": has_seasonality_month_edit,
        "relative_strength_reference_symbol_edit": relative_strength_reference_symbol_edit,
        "relative_strength_lookback_edit": relative_strength_lookback_edit,
        "relative_strength_threshold_edit": relative_strength_threshold_edit,
        "has_partial_relative_strength_edit": has_partial_relative_strength_edit,
        "confirmation_family": confirmation_family,
        "add_confirmation_intent": add_confirmation_intent,
        "remove_confirmation_intent": remove_confirmation_intent,
        "has_confirmation_edit_intent": has_confirmation_edit_intent,
        "entry_window_bars_edit": entry_window_bars_edit,
        "exit_window_bars_edit": exit_window_bars_edit,
        "entry_window_mode_edit": entry_window_mode_edit,
        "exit_window_mode_edit": exit_window_mode_edit,
        "entry_sequence_bars_edit": entry_sequence_bars_edit,
        "exit_sequence_bars_edit": exit_sequence_bars_edit,
        "entry_sequence_first_step_edit": entry_sequence_first_step_edit,
        "entry_sequence_second_step_edit": entry_sequence_second_step_edit,
        "exit_sequence_first_step_edit": exit_sequence_first_step_edit,
        "exit_sequence_second_step_edit": exit_sequence_second_step_edit,
        "has_temporal_rule_edit_intent": has_temporal_rule_edit_intent,
        "entry_group_operator_edit": entry_group_operator_edit,
        "exit_group_operator_edit": exit_group_operator_edit,
        "entry_group_first_condition_edit": entry_group_first_condition_edit,
        "entry_group_second_condition_edit": entry_group_second_condition_edit,
        "exit_group_first_condition_edit": exit_group_first_condition_edit,
        "exit_group_second_condition_edit": exit_group_second_condition_edit,
        "entry_window_inner_rule_edit": entry_window_inner_rule_edit,
        "exit_window_inner_rule_edit": exit_window_inner_rule_edit,
        "entry_not_inner_rule_edit": entry_not_inner_rule_edit,
        "exit_not_inner_rule_edit": exit_not_inner_rule_edit,
        "has_not_rule_edit_intent": has_not_rule_edit_intent,
        "has_nested_composite_edit_intent": has_nested_composite_edit_intent,
        "remove_entry_group_first_condition": remove_entry_group_first_condition,
        "remove_entry_group_second_condition": remove_entry_group_second_condition,
        "remove_exit_group_first_condition": remove_exit_group_first_condition,
        "remove_exit_group_second_condition": remove_exit_group_second_condition,
        "remove_entry_window_wrapper": remove_entry_window_wrapper,
        "remove_exit_window_wrapper": remove_exit_window_wrapper,
        "remove_entry_not_wrapper": remove_entry_not_wrapper,
        "remove_exit_not_wrapper": remove_exit_not_wrapper,
        "remove_entry_sequence_first_step": remove_entry_sequence_first_step,
        "remove_entry_sequence_second_step": remove_entry_sequence_second_step,
        "remove_exit_sequence_first_step": remove_exit_sequence_first_step,
        "remove_exit_sequence_second_step": remove_exit_sequence_second_step,
        "has_nested_composite_removal_intent": has_nested_composite_removal_intent,
    }


def _finalize_rule_setup(
    *,
    prompt: str,
    prompt_lower: str,
    tradable_symbol: str,
    benchmark_symbol: str,
    current_config: dict[str, Any] | None,
    has_current_config: bool,
    assumptions: list[str],
    warnings: list[str],
    entry_rule: dict | None,
    exit_rule: dict | None,
    month_values: list[int] | None,
    has_confirmation_edit_intent: bool,
) -> dict[str, Any]:
    if has_confirmation_edit_intent and not has_current_config:
        raise ValueError(
            "Confirmation filters currently require an existing draft. "
            "Create a base strategy first, then ask me to add or remove "
            "MACD, KD/stochastic, or relative strength confirmation."
        )

    effective_tradable_symbol, effective_benchmark_symbol = _resolve_effective_symbols(
        tradable_symbol=tradable_symbol,
        benchmark_symbol=benchmark_symbol,
        current_config=current_config,
        has_current_config=has_current_config,
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
        tradable_symbol=effective_tradable_symbol,
        fallback_reference_symbol=effective_benchmark_symbol,
    )

    if relative_strength_rules is not None:
        entry_rule, exit_rule, relative_strength_assumptions = relative_strength_rules
        assumptions.extend(relative_strength_assumptions)

    confirmation_rules = None
    if has_confirmation_edit_intent:
        confirmation_rules = _build_confirmation_rules(
            prompt,
            tradable_symbol=effective_tradable_symbol,
            fallback_reference_symbol=effective_benchmark_symbol,
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
            tradable_symbol=effective_tradable_symbol,
            fallback_reference_symbol=effective_benchmark_symbol,
            side="entry",
        )
        composite_exit_rule, composite_exit_assumptions = _build_rule_from_clause(
            exit_clause,
            tradable_symbol=effective_tradable_symbol,
            fallback_reference_symbol=effective_benchmark_symbol,
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

    elif entry_clause is None and exit_clause is None:
        entry_only_clause = _extract_entry_rule_clause(prompt)
        exit_only_clause = _extract_exit_rule_clause(prompt)

        if entry_only_clause is not None:
            composite_entry_rule, composite_entry_assumptions = _build_rule_from_clause(
                entry_only_clause,
                tradable_symbol=effective_tradable_symbol,
                fallback_reference_symbol=effective_benchmark_symbol,
                side="entry",
            )
            if composite_entry_rule is not None:
                entry_rule = composite_entry_rule
                assumptions.extend(composite_entry_assumptions)
                assumptions.append(
                    "Interpreted explicit entry clause as a combined rule using AND/OR."
                )

                if re.search(
                    r"\b(?:only\s+when|while)\b|\bavoid\s+(?:trading|risk[-\s]?on\s+entries|entries)\b",
                    prompt,
                    flags=re.IGNORECASE,
                ):
                    exit_rule = {
                        "kind": "not",
                        "rule": deepcopy(composite_entry_rule),
                    }
                    assumptions.append(
                        "Interpreted regime-filter language as exiting when the entry filter no longer holds."
                    )

        if exit_only_clause is not None:
            composite_exit_rule, composite_exit_assumptions = _build_rule_from_clause(
                exit_only_clause,
                tradable_symbol=effective_tradable_symbol,
                fallback_reference_symbol=effective_benchmark_symbol,
                side="exit",
            )
            if composite_exit_rule is not None:
                exit_rule = composite_exit_rule
                assumptions.extend(composite_exit_assumptions)
                assumptions.append(
                    "Interpreted explicit exit clause as a combined rule using AND/OR."
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

    return {
        "entry_rule": entry_rule,
        "exit_rule": exit_rule,
        "confirmation_rules": confirmation_rules,
    }


def _build_base_rule_candidates(
    *,
    prompt: str,
    prompt_lower: str,
    tradable_symbol: str,
    assumptions: list[str],
) -> dict[str, Any]:
    entry_rule = None
    exit_rule = None

    rsi_buy = _extract_rsi_rule(prompt, direction="below")
    rsi_sell = _extract_rsi_rule(prompt, direction="above")
    volatility_below = _extract_realized_volatility_rule(prompt, direction="below")
    volatility_above = _extract_realized_volatility_rule(prompt, direction="above")
    rsi_entry_threshold_edit = _extract_rsi_entry_threshold_edit(prompt)
    rsi_exit_threshold_edit = _extract_rsi_exit_threshold_edit(prompt)
    rsi_entry_lookback_edit = _extract_rsi_entry_lookback_edit(prompt)
    rsi_exit_lookback_edit = _extract_rsi_exit_lookback_edit(prompt)
    sma_pair = _extract_sma_crossover_pair(prompt)
    sma_above_pair = _extract_sma_above_pair(prompt)
    single_sma_window = _extract_single_sma_window(prompt)

    entry_fast_window_edit = _extract_entry_fast_window_edit(prompt)
    entry_slow_window_edit = _extract_entry_slow_window_edit(prompt)
    exit_fast_window_edit = _extract_exit_fast_window_edit(prompt)
    exit_slow_window_edit = _extract_exit_slow_window_edit(prompt)
    sma_filter_window_edit = _extract_sma_filter_window_edit(prompt)
    if sma_filter_window_edit is not None:
        entry_slow_window_edit = entry_slow_window_edit or sma_filter_window_edit
        exit_slow_window_edit = exit_slow_window_edit or sma_filter_window_edit

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

    if volatility_below:
        lookback, threshold, used_default_lookback = volatility_below
        rule = {
            "kind": "atomic",
            "type": "realized_volatility_below",
            "symbol": tradable_symbol,
            "lookback": lookback,
            "threshold": threshold,
        }
        if used_default_lookback:
            assumptions.append("Used 20 trading days as the realized volatility lookback by default.")
        if _looks_like_exit_only_prompt(prompt):
            exit_rule = rule
        elif entry_rule is None:
            entry_rule = rule

    if volatility_above:
        lookback, threshold, used_default_lookback = volatility_above
        rule = {
            "kind": "atomic",
            "type": "realized_volatility_above",
            "symbol": tradable_symbol,
            "lookback": lookback,
            "threshold": threshold,
        }
        if used_default_lookback:
            assumptions.append("Used 20 trading days as the realized volatility lookback by default.")
        if _looks_like_entry_only_prompt(prompt):
            entry_rule = rule
        elif exit_rule is None:
            exit_rule = rule

    if "moving average" in prompt_lower or "sma" in prompt_lower:
        selected_pair = sma_above_pair if sma_above_pair is not None else sma_pair
        price_sma_rule = (
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": tradable_symbol,
                "fast_window": 1,
                "slow_window": single_sma_window,
            }
            if selected_pair is None
            and single_sma_window is not None
            and (_has_price_above_sma_intent(prompt) or _has_price_below_sma_intent(prompt))
            else None
        )

        if price_sma_rule is not None:
            if _has_price_below_sma_intent(prompt) and not _has_price_above_sma_intent(prompt):
                if exit_rule is None and _looks_like_exit_only_prompt(prompt):
                    exit_rule = {
                        "kind": "not",
                        "rule": price_sma_rule,
                    }
                elif entry_rule is None:
                    entry_rule = {
                        "kind": "not",
                        "rule": price_sma_rule,
                    }
            else:
                if entry_rule is None:
                    entry_rule = price_sma_rule

                if exit_rule is None and not _looks_like_entry_only_prompt(prompt):
                    exit_rule = {
                        "kind": "not",
                        "rule": price_sma_rule,
                    }

            assumptions.append(
                f"Interpreted price-vs-SMA language using {single_sma_window} as the SMA window."
            )
            return {
                "entry_rule": entry_rule,
                "exit_rule": exit_rule,
                "rsi_entry_threshold_edit": rsi_entry_threshold_edit,
                "rsi_exit_threshold_edit": rsi_exit_threshold_edit,
                "rsi_entry_lookback_edit": rsi_entry_lookback_edit,
                "rsi_exit_lookback_edit": rsi_exit_lookback_edit,
                "entry_fast_window_edit": entry_fast_window_edit,
                "entry_slow_window_edit": entry_slow_window_edit,
                "exit_fast_window_edit": exit_fast_window_edit,
                "exit_slow_window_edit": exit_slow_window_edit,
                "has_partial_sma_window_edit": has_partial_sma_window_edit,
            }

        fast_window, slow_window = selected_pair if selected_pair else (20, 50)
        if selected_pair:
            assumptions.append(
                f"Detected moving-average windows {fast_window}/{slow_window}."
            )
        else:
            assumptions.append(
                "Used default moving-average windows 20/50."
            )

        if _has_sma_above_state_intent(prompt):
            if entry_rule is None:
                entry_rule = {
                    "kind": "atomic",
                    "type": "sma_above",
                    "symbol": tradable_symbol,
                    "fast_window": fast_window,
                    "slow_window": slow_window,
                }

            if exit_rule is None:
                exit_rule = {
                    "kind": "not",
                    "rule": {
                        "kind": "atomic",
                        "type": "sma_above",
                        "symbol": tradable_symbol,
                        "fast_window": fast_window,
                        "slow_window": slow_window,
                    },
                }

            assumptions.append(
                "Interpreted 'SMA above' as entering while the fast SMA stays above the slow SMA and exiting when that condition no longer holds."
            )
        else:
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

    return {
        "entry_rule": entry_rule,
        "exit_rule": exit_rule,
        "rsi_entry_threshold_edit": rsi_entry_threshold_edit,
        "rsi_exit_threshold_edit": rsi_exit_threshold_edit,
        "rsi_entry_lookback_edit": rsi_entry_lookback_edit,
        "rsi_exit_lookback_edit": rsi_exit_lookback_edit,
        "entry_fast_window_edit": entry_fast_window_edit,
        "entry_slow_window_edit": entry_slow_window_edit,
        "exit_fast_window_edit": exit_fast_window_edit,
        "exit_slow_window_edit": exit_slow_window_edit,
        "has_partial_sma_window_edit": has_partial_sma_window_edit,
    }


def _build_rule_setup(
    *,
    prompt: str,
    prompt_lower: str,
    tradable_symbol: str,
    benchmark_symbol: str,
    current_config: dict[str, Any] | None,
    has_current_config: bool,
    assumptions: list[str],
    warnings: list[str],
) -> dict[str, Any]:

    base_rule_candidates = _build_base_rule_candidates(
        prompt=prompt,
        prompt_lower=prompt_lower,
        tradable_symbol=tradable_symbol,
        assumptions=assumptions,
    )

    entry_rule = base_rule_candidates["entry_rule"]
    exit_rule = base_rule_candidates["exit_rule"]
    rsi_entry_threshold_edit = base_rule_candidates["rsi_entry_threshold_edit"]
    rsi_exit_threshold_edit = base_rule_candidates["rsi_exit_threshold_edit"]
    rsi_entry_lookback_edit = base_rule_candidates["rsi_entry_lookback_edit"]
    rsi_exit_lookback_edit = base_rule_candidates["rsi_exit_lookback_edit"]
    entry_fast_window_edit = base_rule_candidates["entry_fast_window_edit"]
    entry_slow_window_edit = base_rule_candidates["entry_slow_window_edit"]
    exit_fast_window_edit = base_rule_candidates["exit_fast_window_edit"]
    exit_slow_window_edit = base_rule_candidates["exit_slow_window_edit"]
    has_partial_sma_window_edit = base_rule_candidates["has_partial_sma_window_edit"]

    rule_edit_intents = _extract_rule_edit_intents(
        prompt=prompt,
    )

    month_values = rule_edit_intents["month_values"]
    seasonality_month_edit_action = rule_edit_intents["seasonality_month_edit_action"]
    has_seasonality_month_edit = rule_edit_intents["has_seasonality_month_edit"]
    relative_strength_reference_symbol_edit = rule_edit_intents["relative_strength_reference_symbol_edit"]
    relative_strength_lookback_edit = rule_edit_intents["relative_strength_lookback_edit"]
    relative_strength_threshold_edit = rule_edit_intents["relative_strength_threshold_edit"]
    has_partial_relative_strength_edit = rule_edit_intents["has_partial_relative_strength_edit"]
    confirmation_family = rule_edit_intents["confirmation_family"]
    add_confirmation_intent = rule_edit_intents["add_confirmation_intent"]
    remove_confirmation_intent = rule_edit_intents["remove_confirmation_intent"]
    has_confirmation_edit_intent = rule_edit_intents["has_confirmation_edit_intent"]
    entry_window_bars_edit = rule_edit_intents["entry_window_bars_edit"]
    exit_window_bars_edit = rule_edit_intents["exit_window_bars_edit"]
    entry_window_mode_edit = rule_edit_intents["entry_window_mode_edit"]
    exit_window_mode_edit = rule_edit_intents["exit_window_mode_edit"]
    entry_sequence_bars_edit = rule_edit_intents["entry_sequence_bars_edit"]
    exit_sequence_bars_edit = rule_edit_intents["exit_sequence_bars_edit"]
    entry_sequence_first_step_edit = rule_edit_intents["entry_sequence_first_step_edit"]
    entry_sequence_second_step_edit = rule_edit_intents["entry_sequence_second_step_edit"]
    exit_sequence_first_step_edit = rule_edit_intents["exit_sequence_first_step_edit"]
    exit_sequence_second_step_edit = rule_edit_intents["exit_sequence_second_step_edit"]
    has_temporal_rule_edit_intent = rule_edit_intents["has_temporal_rule_edit_intent"]
    entry_group_operator_edit = rule_edit_intents["entry_group_operator_edit"]
    exit_group_operator_edit = rule_edit_intents["exit_group_operator_edit"]
    entry_group_first_condition_edit = rule_edit_intents["entry_group_first_condition_edit"]
    entry_group_second_condition_edit = rule_edit_intents["entry_group_second_condition_edit"]
    exit_group_first_condition_edit = rule_edit_intents["exit_group_first_condition_edit"]
    exit_group_second_condition_edit = rule_edit_intents["exit_group_second_condition_edit"]
    entry_window_inner_rule_edit = rule_edit_intents["entry_window_inner_rule_edit"]
    exit_window_inner_rule_edit = rule_edit_intents["exit_window_inner_rule_edit"]
    entry_not_inner_rule_edit = rule_edit_intents["entry_not_inner_rule_edit"]
    exit_not_inner_rule_edit = rule_edit_intents["exit_not_inner_rule_edit"]
    has_not_rule_edit_intent = rule_edit_intents["has_not_rule_edit_intent"]
    has_nested_composite_edit_intent = rule_edit_intents["has_nested_composite_edit_intent"]
    remove_entry_group_first_condition = rule_edit_intents["remove_entry_group_first_condition"]
    remove_entry_group_second_condition = rule_edit_intents["remove_entry_group_second_condition"]
    remove_exit_group_first_condition = rule_edit_intents["remove_exit_group_first_condition"]
    remove_exit_group_second_condition = rule_edit_intents["remove_exit_group_second_condition"]
    remove_entry_window_wrapper = rule_edit_intents["remove_entry_window_wrapper"]
    remove_exit_window_wrapper = rule_edit_intents["remove_exit_window_wrapper"]
    remove_entry_not_wrapper = rule_edit_intents["remove_entry_not_wrapper"]
    remove_exit_not_wrapper = rule_edit_intents["remove_exit_not_wrapper"]
    remove_entry_sequence_first_step = rule_edit_intents["remove_entry_sequence_first_step"]
    remove_entry_sequence_second_step = rule_edit_intents["remove_entry_sequence_second_step"]
    remove_exit_sequence_first_step = rule_edit_intents["remove_exit_sequence_first_step"]
    remove_exit_sequence_second_step = rule_edit_intents["remove_exit_sequence_second_step"]
    has_nested_composite_removal_intent = rule_edit_intents["has_nested_composite_removal_intent"]

    finalized_rule_setup = _finalize_rule_setup(
        prompt=prompt,
        prompt_lower=prompt_lower,
        tradable_symbol=tradable_symbol,
        benchmark_symbol=benchmark_symbol,
        current_config=current_config,
        has_current_config=has_current_config,
        assumptions=assumptions,
        warnings=warnings,
        entry_rule=entry_rule,
        exit_rule=exit_rule,
        month_values=month_values,
        has_confirmation_edit_intent=has_confirmation_edit_intent,
    )

    entry_rule = finalized_rule_setup["entry_rule"]
    exit_rule = finalized_rule_setup["exit_rule"]
    confirmation_rules = finalized_rule_setup["confirmation_rules"]

    return {
        "entry_rule": entry_rule,
        "exit_rule": exit_rule,
        "rsi_entry_threshold_edit": rsi_entry_threshold_edit,
        "rsi_exit_threshold_edit": rsi_exit_threshold_edit,
        "rsi_entry_lookback_edit": rsi_entry_lookback_edit,
        "rsi_exit_lookback_edit": rsi_exit_lookback_edit,
        "entry_fast_window_edit": entry_fast_window_edit,
        "entry_slow_window_edit": entry_slow_window_edit,
        "exit_fast_window_edit": exit_fast_window_edit,
        "exit_slow_window_edit": exit_slow_window_edit,
        "has_partial_sma_window_edit": has_partial_sma_window_edit,
        "month_values": month_values,
        "seasonality_month_edit_action": seasonality_month_edit_action,
        "has_seasonality_month_edit": has_seasonality_month_edit,
        "relative_strength_reference_symbol_edit": relative_strength_reference_symbol_edit,
        "relative_strength_lookback_edit": relative_strength_lookback_edit,
        "relative_strength_threshold_edit": relative_strength_threshold_edit,
        "has_partial_relative_strength_edit": has_partial_relative_strength_edit,
        "confirmation_family": confirmation_family,
        "add_confirmation_intent": add_confirmation_intent,
        "remove_confirmation_intent": remove_confirmation_intent,
        "has_confirmation_edit_intent": has_confirmation_edit_intent,
        "confirmation_rules": confirmation_rules,
        "entry_window_bars_edit": entry_window_bars_edit,
        "exit_window_bars_edit": exit_window_bars_edit,
        "entry_window_mode_edit": entry_window_mode_edit,
        "exit_window_mode_edit": exit_window_mode_edit,
        "entry_sequence_bars_edit": entry_sequence_bars_edit,
        "exit_sequence_bars_edit": exit_sequence_bars_edit,
        "entry_sequence_first_step_edit": entry_sequence_first_step_edit,
        "entry_sequence_second_step_edit": entry_sequence_second_step_edit,
        "exit_sequence_first_step_edit": exit_sequence_first_step_edit,
        "exit_sequence_second_step_edit": exit_sequence_second_step_edit,
        "has_temporal_rule_edit_intent": has_temporal_rule_edit_intent,
        "entry_group_operator_edit": entry_group_operator_edit,
        "exit_group_operator_edit": exit_group_operator_edit,
        "entry_group_first_condition_edit": entry_group_first_condition_edit,
        "entry_group_second_condition_edit": entry_group_second_condition_edit,
        "exit_group_first_condition_edit": exit_group_first_condition_edit,
        "exit_group_second_condition_edit": exit_group_second_condition_edit,
        "entry_window_inner_rule_edit": entry_window_inner_rule_edit,
        "exit_window_inner_rule_edit": exit_window_inner_rule_edit,
        "entry_not_inner_rule_edit": entry_not_inner_rule_edit,
        "exit_not_inner_rule_edit": exit_not_inner_rule_edit,
        "has_not_rule_edit_intent": has_not_rule_edit_intent,
        "has_nested_composite_edit_intent": has_nested_composite_edit_intent,
        "remove_entry_group_first_condition": remove_entry_group_first_condition,
        "remove_entry_group_second_condition": remove_entry_group_second_condition,
        "remove_exit_group_first_condition": remove_exit_group_first_condition,
        "remove_exit_group_second_condition": remove_exit_group_second_condition,
        "remove_entry_window_wrapper": remove_entry_window_wrapper,
        "remove_exit_window_wrapper": remove_exit_window_wrapper,
        "remove_entry_not_wrapper": remove_entry_not_wrapper,
        "remove_exit_not_wrapper": remove_exit_not_wrapper,
        "remove_entry_sequence_first_step": remove_entry_sequence_first_step,
        "remove_entry_sequence_second_step": remove_entry_sequence_second_step,
        "remove_exit_sequence_first_step": remove_exit_sequence_first_step,
        "remove_exit_sequence_second_step": remove_exit_sequence_second_step,
        "has_nested_composite_removal_intent": has_nested_composite_removal_intent,
    }


def _apply_update_flow_edits(
    *,
    default_config: dict[str, Any],
    base_config: dict[str, Any],
    has_current_config: bool,
    prompt: str,
    prompt_lower: str,
    tradable_symbol: str,
    benchmark_symbol: str,
    tradable_symbol_edit: str | None,
    initial_capital: float,
    allocation_value: float,
    allocation_edit_value: float | None,
    max_position_pct_edit: float | None,
    overlay_allocation_pct: float | None,
    transaction_cost_bps_edit: float | None,
    stop_loss_removed: bool,
    stop_loss_pct: float | None,
    take_profit_removed: bool,
    take_profit_pct: float | None,
    cooldown_removed: bool,
    cooldown_edit: int | None,
    cooldown_bars: int,
    partial_take_profit_removed: bool,
    partial_take_profit: dict[str, Any] | None,
    scale_in_fraction_edit: float | None,
    scale_out_fraction_edit: float | None,
    profit_reduce_threshold_edit: float | None,
    position_management_removed: bool,
    has_position_management_edit: bool,
    core_overlay_enabled: bool,
    core_overlay_disabled: bool,
    core_allocation_pct: float | None,
    entry_rule: dict | None,
    exit_rule: dict | None,
    rsi_entry_threshold_edit: float | None,
    rsi_exit_threshold_edit: float | None,
    rsi_entry_lookback_edit: int | None,
    rsi_exit_lookback_edit: int | None,
    entry_fast_window_edit: int | None,
    entry_slow_window_edit: int | None,
    exit_fast_window_edit: int | None,
    exit_slow_window_edit: int | None,
    has_partial_sma_window_edit: bool,
    month_values: list[int] | None,
    seasonality_month_edit_action: str | None,
    has_seasonality_month_edit: bool,
    has_partial_relative_strength_edit: bool,
    relative_strength_reference_symbol_edit: str | None,
    relative_strength_lookback_edit: int | None,
    relative_strength_threshold_edit: float | None,
    confirmation_family: str | None,
    add_confirmation_intent: bool,
    remove_confirmation_intent: bool,
    has_confirmation_edit_intent: bool,
    confirmation_rules: tuple[dict, dict, list[str]] | None,
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
    has_temporal_rule_edit_intent: bool,
    entry_group_operator_edit: str | None,
    exit_group_operator_edit: str | None,
    entry_group_first_condition_edit: str | None,
    entry_group_second_condition_edit: str | None,
    exit_group_first_condition_edit: str | None,
    exit_group_second_condition_edit: str | None,
    entry_window_inner_rule_edit: str | None,
    exit_window_inner_rule_edit: str | None,
    has_nested_composite_edit_intent: bool,
    entry_not_inner_rule_edit: str | None,
    exit_not_inner_rule_edit: str | None,
    has_not_rule_edit_intent: bool,
    remove_entry_group_first_condition: bool,
    remove_entry_group_second_condition: bool,
    remove_exit_group_first_condition: bool,
    remove_exit_group_second_condition: bool,
    remove_entry_window_wrapper: bool,
    remove_exit_window_wrapper: bool,
    remove_entry_not_wrapper: bool,
    remove_exit_not_wrapper: bool,
    remove_entry_sequence_first_step: bool,
    remove_entry_sequence_second_step: bool,
    remove_exit_sequence_first_step: bool,
    remove_exit_sequence_second_step: bool,
    has_nested_composite_removal_intent: bool,
    assumptions: list[str],
) -> dict[str, Any]:
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

    applied_entry_rsi_edit = False
    applied_exit_rsi_edit = False
    applied_entry_moving_average_edit = False
    applied_exit_moving_average_edit = False

    if (
        rsi_entry_threshold_edit is not None or rsi_entry_lookback_edit is not None
    ) and _has_rsi_rule(existing_entry_rule, rule_type="rsi_below"):
        updated_entry_rule = _update_rsi_rules(
            existing_entry_rule,
            rule_type="rsi_below",
            threshold_edit=rsi_entry_threshold_edit,
            lookback_edit=rsi_entry_lookback_edit,
        )
        default_config["entry_rule"] = updated_entry_rule
        existing_entry_rule = updated_entry_rule
        applied_entry_rsi_edit = True

    if (
        rsi_exit_threshold_edit is not None or rsi_exit_lookback_edit is not None
    ) and _has_rsi_rule(existing_exit_rule, rule_type="rsi_above"):
        updated_exit_rule = _update_rsi_rules(
            existing_exit_rule,
            rule_type="rsi_above",
            threshold_edit=rsi_exit_threshold_edit,
            lookback_edit=rsi_exit_lookback_edit,
        )
        default_config["exit_rule"] = updated_exit_rule
        existing_exit_rule = updated_exit_rule
        applied_exit_rsi_edit = True

    if (
        entry_fast_window_edit is not None or entry_slow_window_edit is not None
    ) and _has_moving_average_rule(existing_entry_rule):
        updated_entry_rule = _update_moving_average_rules(
            existing_entry_rule,
            fast_window_edit=entry_fast_window_edit,
            slow_window_edit=entry_slow_window_edit,
        )
        default_config["entry_rule"] = updated_entry_rule
        existing_entry_rule = updated_entry_rule
        applied_entry_moving_average_edit = True

    if (
        exit_fast_window_edit is not None or exit_slow_window_edit is not None
    ) and _has_moving_average_rule(existing_exit_rule):
        updated_exit_rule = _update_moving_average_rules(
            existing_exit_rule,
            fast_window_edit=exit_fast_window_edit,
            slow_window_edit=exit_slow_window_edit,
        )
        default_config["exit_rule"] = updated_exit_rule
        existing_exit_rule = updated_exit_rule
        applied_exit_moving_average_edit = True

    if (
        has_current_config
        and month_values is not None
        and seasonality_month_edit_action is not None
        and (_has_month_in_rule(existing_entry_rule) or _has_month_in_rule(existing_exit_rule))
    ):
        has_seasonality_month_edit = True

        updated_entry_rule = _update_month_in_rules(
            existing_entry_rule,
            action=seasonality_month_edit_action,
            month_values=month_values,
        )
        updated_exit_rule = _update_month_in_rules(
            existing_exit_rule,
            action=seasonality_month_edit_action,
            month_values=month_values,
        )

        default_config["entry_rule"] = updated_entry_rule
        default_config["exit_rule"] = updated_exit_rule

        existing_entry_rule = updated_entry_rule
        existing_exit_rule = updated_exit_rule

        assumptions.append(
            f"Applied seasonality month edit using action '{seasonality_month_edit_action}'."
        )

    if has_partial_relative_strength_edit:
        if _has_relative_strength_rule(existing_entry_rule) or _has_relative_strength_rule(existing_exit_rule):
            updated_entry_rule = _update_relative_strength_rules(
                existing_entry_rule,
                reference_symbol_edit=relative_strength_reference_symbol_edit,
                lookback_edit=relative_strength_lookback_edit,
                threshold_edit=relative_strength_threshold_edit,
            )
            updated_exit_rule = _update_relative_strength_rules(
                existing_exit_rule,
                reference_symbol_edit=relative_strength_reference_symbol_edit,
                lookback_edit=relative_strength_lookback_edit,
                threshold_edit=relative_strength_threshold_edit,
            )

            default_config["entry_rule"] = updated_entry_rule
            default_config["exit_rule"] = updated_exit_rule

            existing_entry_rule = updated_entry_rule
            existing_exit_rule = updated_exit_rule

    if has_temporal_rule_edit_intent:
        current_tradable_symbol, current_benchmark_symbol = _resolve_effective_symbols(
            tradable_symbol=tradable_symbol,
            benchmark_symbol=benchmark_symbol,
            current_config=default_config,
            has_current_config=True,
        )

        if entry_window_bars_edit is not None:
            existing_entry_rule, changed = _update_first_window_bars(
                existing_entry_rule,
                window_bars=entry_window_bars_edit,
            )
            if changed:
                default_config["entry_rule"] = existing_entry_rule

        if entry_window_mode_edit is not None:
            existing_entry_rule, changed = _update_first_window_mode(
                existing_entry_rule,
                mode=entry_window_mode_edit,
            )
            if changed:
                default_config["entry_rule"] = existing_entry_rule

        if exit_window_bars_edit is not None:
            existing_exit_rule, changed = _update_first_window_bars(
                existing_exit_rule,
                window_bars=exit_window_bars_edit,
            )
            if changed:
                default_config["exit_rule"] = existing_exit_rule

        if exit_window_mode_edit is not None:
            existing_exit_rule, changed = _update_first_window_mode(
                existing_exit_rule,
                mode=exit_window_mode_edit,
            )
            if changed:
                default_config["exit_rule"] = existing_exit_rule

        if entry_sequence_bars_edit is not None:
            existing_entry_rule, changed = _update_first_sequence_bars(
                existing_entry_rule,
                window_bars=entry_sequence_bars_edit,
            )
            if changed:
                default_config["entry_rule"] = existing_entry_rule

        if exit_sequence_bars_edit is not None:
            existing_exit_rule, changed = _update_first_sequence_bars(
                existing_exit_rule,
                window_bars=exit_sequence_bars_edit,
            )
            if changed:
                default_config["exit_rule"] = existing_exit_rule

        if entry_sequence_first_step_edit is not None:
            updated_step, step_assumptions = _build_rule_from_clause(
                entry_sequence_first_step_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="entry",
            )
            if updated_step is not None:
                existing_entry_rule, changed = _update_first_sequence_step(
                    existing_entry_rule,
                    index=0,
                    new_step=updated_step,
                )
                if changed:
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(step_assumptions)

        if entry_sequence_second_step_edit is not None:
            updated_step, step_assumptions = _build_rule_from_clause(
                entry_sequence_second_step_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="entry",
            )
            if updated_step is not None:
                existing_entry_rule, changed = _update_first_sequence_step(
                    existing_entry_rule,
                    index=1,
                    new_step=updated_step,
                )
                if changed:
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(step_assumptions)

        if exit_sequence_first_step_edit is not None:
            updated_step, step_assumptions = _build_rule_from_clause(
                exit_sequence_first_step_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="exit",
            )
            if updated_step is not None:
                existing_exit_rule, changed = _update_first_sequence_step(
                    existing_exit_rule,
                    index=0,
                    new_step=updated_step,
                )
                if changed:
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(step_assumptions)

        if exit_sequence_second_step_edit is not None:
            updated_step, step_assumptions = _build_rule_from_clause(
                exit_sequence_second_step_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="exit",
            )
            if updated_step is not None:
                existing_exit_rule, changed = _update_first_sequence_step(
                    existing_exit_rule,
                    index=1,
                    new_step=updated_step,
                )
                if changed:
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(step_assumptions)

    if has_nested_composite_edit_intent:
        current_tradable_symbol, current_benchmark_symbol = _resolve_effective_symbols(
            tradable_symbol=tradable_symbol,
            benchmark_symbol=benchmark_symbol,
            current_config=default_config,
            has_current_config=True,
        )

        if entry_group_operator_edit is not None:
            existing_entry_rule, changed = _update_first_group_operator(
                existing_entry_rule,
                operator=entry_group_operator_edit,
            )
            if changed:
                default_config["entry_rule"] = existing_entry_rule

        if exit_group_operator_edit is not None:
            existing_exit_rule, changed = _update_first_group_operator(
                existing_exit_rule,
                operator=exit_group_operator_edit,
            )
            if changed:
                default_config["exit_rule"] = existing_exit_rule

        if entry_group_first_condition_edit is not None:
            updated_rule, rule_assumptions = _build_rule_from_clause(
                entry_group_first_condition_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="entry",
            )
            if updated_rule is not None:
                existing_entry_rule, changed = _update_first_group_condition(
                    existing_entry_rule,
                    index=0,
                    new_rule=updated_rule,
                )
                if changed:
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(rule_assumptions)

        if entry_group_second_condition_edit is not None:
            updated_rule, rule_assumptions = _build_rule_from_clause(
                entry_group_second_condition_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="entry",
            )
            if updated_rule is not None:
                existing_entry_rule, changed = _update_first_group_condition(
                    existing_entry_rule,
                    index=1,
                    new_rule=updated_rule,
                )
                if changed:
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(rule_assumptions)

        if exit_group_first_condition_edit is not None:
            updated_rule, rule_assumptions = _build_rule_from_clause(
                exit_group_first_condition_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="exit",
            )
            if updated_rule is not None:
                existing_exit_rule, changed = _update_first_group_condition(
                    existing_exit_rule,
                    index=0,
                    new_rule=updated_rule,
                )
                if changed:
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(rule_assumptions)

        if exit_group_second_condition_edit is not None:
            updated_rule, rule_assumptions = _build_rule_from_clause(
                exit_group_second_condition_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="exit",
            )
            if updated_rule is not None:
                existing_exit_rule, changed = _update_first_group_condition(
                    existing_exit_rule,
                    index=1,
                    new_rule=updated_rule,
                )
                if changed:
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(rule_assumptions)

        if entry_window_inner_rule_edit is not None:
            updated_rule, rule_assumptions = _build_rule_from_clause(
                entry_window_inner_rule_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="entry",
            )
            if updated_rule is not None:
                existing_entry_rule, changed = _update_first_window_inner_rule(
                    existing_entry_rule,
                    new_inner_rule=updated_rule,
                )
                if changed:
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(rule_assumptions)

        if exit_window_inner_rule_edit is not None:
            updated_rule, rule_assumptions = _build_rule_from_clause(
                exit_window_inner_rule_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="exit",
            )
            if updated_rule is not None:
                existing_exit_rule, changed = _update_first_window_inner_rule(
                    existing_exit_rule,
                    new_inner_rule=updated_rule,
                )
                if changed:
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(rule_assumptions)

    if has_not_rule_edit_intent:
        current_tradable_symbol, current_benchmark_symbol = _resolve_effective_symbols(
            tradable_symbol=tradable_symbol,
            benchmark_symbol=benchmark_symbol,
            current_config=default_config,
            has_current_config=True,
        )

        if entry_not_inner_rule_edit is not None and _has_not_rule_anywhere(existing_entry_rule):
            updated_rule, rule_assumptions = _build_rule_from_clause(
                entry_not_inner_rule_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="entry",
            )
            if updated_rule is not None:
                existing_entry_rule, changed = _update_first_not_inner_rule(
                    existing_entry_rule,
                    new_inner_rule=updated_rule,
                )
                if changed:
                    default_config["entry_rule"] = existing_entry_rule
                    assumptions.extend(rule_assumptions)

        if exit_not_inner_rule_edit is not None and _has_not_rule_anywhere(existing_exit_rule):
            updated_rule, rule_assumptions = _build_rule_from_clause(
                exit_not_inner_rule_edit,
                tradable_symbol=current_tradable_symbol,
                fallback_reference_symbol=current_benchmark_symbol,
                side="exit",
            )
            if updated_rule is not None:
                existing_exit_rule, changed = _update_first_not_inner_rule(
                    existing_exit_rule,
                    new_inner_rule=updated_rule,
                )
                if changed:
                    default_config["exit_rule"] = existing_exit_rule
                    assumptions.extend(rule_assumptions)

    risk = dict(default_config.get("risk", {}))
    risk.setdefault("cooldown_bars", 0)
    default_config["risk"] = risk

    if _has_benchmark_edit_intent(prompt):
        default_config["benchmark_symbol"] = benchmark_symbol

    if re.search(r"(?:capital|start with|\$)", prompt_lower):
        default_config["initial_capital"] = initial_capital

    if transaction_cost_bps_edit is not None:
        default_config["transaction_cost_bps"] = transaction_cost_bps_edit

    if (
        allocation_edit_value is not None
        or max_position_pct_edit is not None
        or overlay_allocation_pct is not None
        or re.search(r"%\s+of\s+equity|allocation|allocate|max\s+position", prompt_lower)
    ):
        allocation = dict(default_config.get("allocation", {}))
        allocation["entry_mode"] = "percent_of_equity"
        if (
            overlay_allocation_pct is not None
            or allocation_edit_value is not None
            or re.search(r"%\s+of\s+equity|allocation|allocate", prompt_lower)
        ):
            allocation["entry_value"] = (
                overlay_allocation_pct
                if overlay_allocation_pct is not None
                else allocation_edit_value
                if allocation_edit_value is not None
                else allocation_value
            )
        allocation.setdefault("max_position_pct", 1.0)
        if overlay_allocation_pct is not None:
            allocation["max_position_pct"] = overlay_allocation_pct
        elif max_position_pct_edit is not None:
            allocation["max_position_pct"] = max_position_pct_edit
        default_config["allocation"] = allocation

    if (
        entry_fast_window_edit is not None or entry_slow_window_edit is not None
    ) and not applied_entry_moving_average_edit:
        if existing_entry_rule.get("type") in {"sma_cross_above", "sma_cross_below", "sma_above"}:
            if entry_fast_window_edit is not None:
                existing_entry_rule["fast_window"] = entry_fast_window_edit
            if entry_slow_window_edit is not None:
                existing_entry_rule["slow_window"] = entry_slow_window_edit
            default_config["entry_rule"] = existing_entry_rule

    if (
        exit_fast_window_edit is not None or exit_slow_window_edit is not None
    ) and not applied_exit_moving_average_edit:
        if existing_exit_rule.get("type") in {"sma_cross_above", "sma_cross_below", "sma_above"}:
            if exit_fast_window_edit is not None:
                existing_exit_rule["fast_window"] = exit_fast_window_edit
            if exit_slow_window_edit is not None:
                existing_exit_rule["slow_window"] = exit_slow_window_edit
            default_config["exit_rule"] = existing_exit_rule

    if (rsi_entry_threshold_edit is not None or rsi_entry_lookback_edit is not None) and not applied_entry_rsi_edit:
        if existing_entry_rule.get("type") == "rsi_below":
            if rsi_entry_threshold_edit is not None:
                existing_entry_rule["threshold"] = rsi_entry_threshold_edit
            if rsi_entry_lookback_edit is not None:
                existing_entry_rule["lookback"] = rsi_entry_lookback_edit
            existing_entry_rule.setdefault("lookback", 14)
            existing_entry_rule.setdefault("kind", "atomic")
            default_config["entry_rule"] = existing_entry_rule
        elif (
            rsi_entry_threshold_edit is not None
            and rsi_entry_lookback_edit is None
            and _has_numeric_threshold(existing_entry_rule)
        ):
            existing_entry_rule["threshold"] = rsi_entry_threshold_edit
            default_config["entry_rule"] = existing_entry_rule
        elif (
            "rsi" not in prompt_lower
            and rsi_entry_threshold_edit is not None
            and rsi_entry_lookback_edit is None
        ):
            pass
        else:
            default_config["entry_rule"] = {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": default_config.get("tradable_symbol", tradable_symbol),
                "lookback": rsi_entry_lookback_edit if rsi_entry_lookback_edit is not None else 14,
                "threshold": rsi_entry_threshold_edit if rsi_entry_threshold_edit is not None else 30,
            }

    elif entry_rule is not None and not has_partial_sma_window_edit and not has_partial_relative_strength_edit and not has_confirmation_edit_intent and not has_temporal_rule_edit_intent and not has_nested_composite_edit_intent and not has_not_rule_edit_intent and not has_seasonality_month_edit and not has_nested_composite_removal_intent and (
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
        or "volatility" in prompt_lower
        or _looks_like_reference_series_filter_intent(prompt)
    ):
        default_config["entry_rule"] = entry_rule

    if (rsi_exit_threshold_edit is not None or rsi_exit_lookback_edit is not None) and not applied_exit_rsi_edit:
        if existing_exit_rule.get("type") == "rsi_above":
            if rsi_exit_threshold_edit is not None:
                existing_exit_rule["threshold"] = rsi_exit_threshold_edit
            if rsi_exit_lookback_edit is not None:
                existing_exit_rule["lookback"] = rsi_exit_lookback_edit
            existing_exit_rule.setdefault("lookback", 14)
            existing_exit_rule.setdefault("kind", "atomic")
            default_config["exit_rule"] = existing_exit_rule
        elif (
            rsi_exit_threshold_edit is not None
            and rsi_exit_lookback_edit is None
            and _has_numeric_threshold(existing_exit_rule)
        ):
            existing_exit_rule["threshold"] = rsi_exit_threshold_edit
            default_config["exit_rule"] = existing_exit_rule
        elif (
            "rsi" not in prompt_lower
            and rsi_exit_threshold_edit is not None
            and rsi_exit_lookback_edit is None
        ):
            pass
        else:
            default_config["exit_rule"] = {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": default_config.get("tradable_symbol", tradable_symbol),
                "lookback": rsi_exit_lookback_edit if rsi_exit_lookback_edit is not None else 14,
                "threshold": rsi_exit_threshold_edit if rsi_exit_threshold_edit is not None else 70,
            }

    elif exit_rule is not None and not has_partial_sma_window_edit and not has_partial_relative_strength_edit and not has_confirmation_edit_intent and not has_temporal_rule_edit_intent and not has_nested_composite_edit_intent and not has_not_rule_edit_intent and not has_seasonality_month_edit and not has_nested_composite_removal_intent and (
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
        or "volatility" in prompt_lower
        or _looks_like_reference_series_filter_intent(prompt)
    ):
        default_config["exit_rule"] = exit_rule

    if has_confirmation_edit_intent:
        current_entry_rule = dict(default_config.get("entry_rule", {}))
        current_exit_rule = dict(default_config.get("exit_rule", {}))

        if add_confirmation_intent and confirmation_rules is not None:
            entry_confirmation_rule, exit_confirmation_rule, _ = confirmation_rules

            if _has_confirmation_rule(
                current_entry_rule,
                family=confirmation_family,
                side="entry",
            ):
                default_config["entry_rule"] = current_entry_rule
            else:
                updated_entry_rule, changed = _try_add_confirmation_rule_recursively(
                    current_entry_rule,
                    confirmation_rule=entry_confirmation_rule,
                    family=confirmation_family,
                    side="entry",
                )
                default_config["entry_rule"] = (
                    updated_entry_rule
                    if changed
                    else _add_confirmation_rule(
                        current_entry_rule,
                        entry_confirmation_rule,
                    )
                )

            if _has_confirmation_rule(
                current_exit_rule,
                family=confirmation_family,
                side="exit",
            ):
                default_config["exit_rule"] = current_exit_rule
            else:
                updated_exit_rule, changed = _try_add_confirmation_rule_recursively(
                    current_exit_rule,
                    confirmation_rule=exit_confirmation_rule,
                    family=confirmation_family,
                    side="exit",
                )
                default_config["exit_rule"] = (
                    updated_exit_rule
                    if changed
                    else _add_confirmation_rule(
                        current_exit_rule,
                        exit_confirmation_rule,
                    )
                )

        elif remove_confirmation_intent and confirmation_family is not None:
            if _has_confirmation_rule(
                current_entry_rule,
                family=confirmation_family,
                side="entry",
            ):
                default_config["entry_rule"] = _remove_confirmation_rule(
                    current_entry_rule,
                    family=confirmation_family,
                    side="entry",
                )

            if _has_confirmation_rule(
                current_exit_rule,
                family=confirmation_family,
                side="exit",
            ):
                default_config["exit_rule"] = _remove_confirmation_rule(
                    current_exit_rule,
                    family=confirmation_family,
                    side="exit",
                )

    if has_nested_composite_removal_intent:
        if remove_entry_group_first_condition:
            updated_entry_rule, changed = _remove_first_group_condition(
                existing_entry_rule,
                index=0,
            )
            if changed:
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

        if remove_entry_group_second_condition:
            updated_entry_rule, changed = _remove_first_group_condition(
                existing_entry_rule,
                index=1,
            )
            if changed:
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

        if remove_exit_group_first_condition:
            updated_exit_rule, changed = _remove_first_group_condition(
                existing_exit_rule,
                index=0,
            )
            if changed:
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

        if remove_exit_group_second_condition:
            updated_exit_rule, changed = _remove_first_group_condition(
                existing_exit_rule,
                index=1,
            )
            if changed:
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

        if remove_entry_not_wrapper:
            updated_entry_rule, changed = _remove_first_not_wrapper(existing_entry_rule)
            if changed:
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

        if remove_exit_not_wrapper:
            updated_exit_rule, changed = _remove_first_not_wrapper(existing_exit_rule)
            if changed:
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

        if remove_entry_window_wrapper:
            updated_entry_rule, changed = _remove_first_window_wrapper(existing_entry_rule)
            if changed:
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

        if remove_exit_window_wrapper:
            updated_exit_rule, changed = _remove_first_window_wrapper(existing_exit_rule)
            if changed:
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

        if remove_entry_sequence_first_step:
            updated_entry_rule, changed = _remove_first_sequence_step(
                existing_entry_rule,
                index=0,
            )
            if changed:
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

        if remove_entry_sequence_second_step:
            updated_entry_rule, changed = _remove_first_sequence_step(
                existing_entry_rule,
                index=1,
            )
            if changed:
                default_config["entry_rule"] = updated_entry_rule
                existing_entry_rule = updated_entry_rule

        if remove_exit_sequence_first_step:
            updated_exit_rule, changed = _remove_first_sequence_step(
                existing_exit_rule,
                index=0,
            )
            if changed:
                default_config["exit_rule"] = updated_exit_rule
                existing_exit_rule = updated_exit_rule

        if remove_exit_sequence_second_step:
            updated_exit_rule, changed = _remove_first_sequence_step(
                existing_exit_rule,
                index=1,
            )
            if changed:
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
    return default_config


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

    core_inputs = _extract_core_prompt_inputs(
        prompt=prompt,
        max_backtest_years=max_backtest_years,
        assumptions=assumptions,
        has_current_config=has_current_config,
    )

    tradable_symbol = core_inputs["tradable_symbol"]
    benchmark_symbol = core_inputs["benchmark_symbol"]
    tradable_symbol_edit = core_inputs["tradable_symbol_edit"]
    reference_symbols = core_inputs["reference_symbols"]
    start_date = core_inputs["start_date"]
    end_date = core_inputs["end_date"]
    initial_capital = core_inputs["initial_capital"]
    allocation_edit_value = core_inputs["allocation_edit_value"]
    max_position_pct_edit = core_inputs["max_position_pct_edit"]
    transaction_cost_bps_edit = core_inputs["transaction_cost_bps_edit"]
    allocation_value = core_inputs["allocation_value"]
    explicit_date_edits = core_inputs["explicit_date_edits"]

    risk_and_position = _extract_risk_and_position_inputs(
        prompt=prompt,
        assumptions=assumptions,
    )

    stop_loss_removed = risk_and_position["stop_loss_removed"]
    stop_loss_pct = risk_and_position["stop_loss_pct"]
    take_profit_removed = risk_and_position["take_profit_removed"]
    take_profit_pct = risk_and_position["take_profit_pct"]
    cooldown_removed = risk_and_position["cooldown_removed"]
    cooldown_edit = risk_and_position["cooldown_edit"]
    cooldown_bars = risk_and_position["cooldown_bars"]
    partial_take_profit_removed = risk_and_position["partial_take_profit_removed"]
    partial_take_profit = risk_and_position["partial_take_profit"]
    scale_in_fraction_edit = risk_and_position["scale_in_fraction_edit"]
    scale_out_fraction_edit = risk_and_position["scale_out_fraction_edit"]
    profit_reduce_threshold_edit = risk_and_position["profit_reduce_threshold_edit"]
    position_management_removed = risk_and_position["position_management_removed"]
    has_position_management_edit = risk_and_position["has_position_management_edit"]
    core_allocation_pct = risk_and_position["core_allocation_pct"]
    core_overlay_disabled = risk_and_position["core_overlay_disabled"]
    core_overlay_enabled = risk_and_position["core_overlay_enabled"]
    overlay_allocation_pct = risk_and_position["overlay_allocation_pct"]

    add_reduce_reference_series_setup = _extract_add_reduce_reference_series_setup(
        prompt,
        tradable_symbol=tradable_symbol,
        benchmark_symbol=benchmark_symbol,
    )

    rule_setup = _build_rule_setup(
        prompt=prompt,
        prompt_lower=prompt_lower,
        tradable_symbol=tradable_symbol,
        benchmark_symbol=benchmark_symbol,
        current_config=current_config,
        has_current_config=has_current_config,
        assumptions=assumptions,
        warnings=warnings,
    )

    entry_rule = rule_setup["entry_rule"]
    exit_rule = rule_setup["exit_rule"]
    rsi_entry_threshold_edit = rule_setup["rsi_entry_threshold_edit"]
    rsi_exit_threshold_edit = rule_setup["rsi_exit_threshold_edit"]
    rsi_entry_lookback_edit = rule_setup["rsi_entry_lookback_edit"]
    rsi_exit_lookback_edit = rule_setup["rsi_exit_lookback_edit"]
    entry_fast_window_edit = rule_setup["entry_fast_window_edit"]
    entry_slow_window_edit = rule_setup["entry_slow_window_edit"]
    exit_fast_window_edit = rule_setup["exit_fast_window_edit"]
    exit_slow_window_edit = rule_setup["exit_slow_window_edit"]
    has_partial_sma_window_edit = rule_setup["has_partial_sma_window_edit"]
    month_values = rule_setup["month_values"]
    seasonality_month_edit_action = rule_setup["seasonality_month_edit_action"]
    has_seasonality_month_edit = rule_setup["has_seasonality_month_edit"]
    relative_strength_reference_symbol_edit = rule_setup["relative_strength_reference_symbol_edit"]
    relative_strength_lookback_edit = rule_setup["relative_strength_lookback_edit"]
    relative_strength_threshold_edit = rule_setup["relative_strength_threshold_edit"]
    has_partial_relative_strength_edit = rule_setup["has_partial_relative_strength_edit"]
    confirmation_family = rule_setup["confirmation_family"]
    add_confirmation_intent = rule_setup["add_confirmation_intent"]
    remove_confirmation_intent = rule_setup["remove_confirmation_intent"]
    has_confirmation_edit_intent = rule_setup["has_confirmation_edit_intent"]
    confirmation_rules = rule_setup["confirmation_rules"]
    entry_window_bars_edit = rule_setup["entry_window_bars_edit"]
    exit_window_bars_edit = rule_setup["exit_window_bars_edit"]
    entry_window_mode_edit = rule_setup["entry_window_mode_edit"]
    exit_window_mode_edit = rule_setup["exit_window_mode_edit"]
    entry_sequence_bars_edit = rule_setup["entry_sequence_bars_edit"]
    exit_sequence_bars_edit = rule_setup["exit_sequence_bars_edit"]
    entry_sequence_first_step_edit = rule_setup["entry_sequence_first_step_edit"]
    entry_sequence_second_step_edit = rule_setup["entry_sequence_second_step_edit"]
    exit_sequence_first_step_edit = rule_setup["exit_sequence_first_step_edit"]
    exit_sequence_second_step_edit = rule_setup["exit_sequence_second_step_edit"]
    has_temporal_rule_edit_intent = rule_setup["has_temporal_rule_edit_intent"]
    entry_group_operator_edit = rule_setup["entry_group_operator_edit"]
    exit_group_operator_edit = rule_setup["exit_group_operator_edit"]
    entry_group_first_condition_edit = rule_setup["entry_group_first_condition_edit"]
    entry_group_second_condition_edit = rule_setup["entry_group_second_condition_edit"]
    exit_group_first_condition_edit = rule_setup["exit_group_first_condition_edit"]
    exit_group_second_condition_edit = rule_setup["exit_group_second_condition_edit"]
    entry_window_inner_rule_edit = rule_setup["entry_window_inner_rule_edit"]
    exit_window_inner_rule_edit = rule_setup["exit_window_inner_rule_edit"]
    entry_not_inner_rule_edit = rule_setup["entry_not_inner_rule_edit"]
    exit_not_inner_rule_edit = rule_setup["exit_not_inner_rule_edit"]
    has_not_rule_edit_intent = rule_setup["has_not_rule_edit_intent"]
    has_nested_composite_edit_intent = rule_setup["has_nested_composite_edit_intent"]
    remove_entry_group_first_condition = rule_setup["remove_entry_group_first_condition"]
    remove_entry_group_second_condition = rule_setup["remove_entry_group_second_condition"]
    remove_exit_group_first_condition = rule_setup["remove_exit_group_first_condition"]
    remove_exit_group_second_condition = rule_setup["remove_exit_group_second_condition"]
    remove_entry_window_wrapper = rule_setup["remove_entry_window_wrapper"]
    remove_exit_window_wrapper = rule_setup["remove_exit_window_wrapper"]
    remove_entry_not_wrapper = rule_setup["remove_entry_not_wrapper"]
    remove_exit_not_wrapper = rule_setup["remove_exit_not_wrapper"]
    remove_entry_sequence_first_step = rule_setup["remove_entry_sequence_first_step"]
    remove_entry_sequence_second_step = rule_setup["remove_entry_sequence_second_step"]
    remove_exit_sequence_first_step = rule_setup["remove_exit_sequence_first_step"]
    remove_exit_sequence_second_step = rule_setup["remove_exit_sequence_second_step"]
    has_nested_composite_removal_intent = rule_setup["has_nested_composite_removal_intent"]

    if add_reduce_reference_series_setup is not None:
        entry_rule = add_reduce_reference_series_setup["entry_rule"]
        exit_rule = add_reduce_reference_series_setup["exit_rule"]
        warnings = [
            warning
            for warning in warnings
            if warning
            not in {
                "Entry rule defaulted to RSI(14) below 30.",
                "Exit rule defaulted to RSI(14) above 70.",
            }
        ]

        for reference_symbol in add_reduce_reference_series_setup["reference_symbols"]:
            if reference_symbol not in reference_symbols:
                reference_symbols.append(reference_symbol)

        if re.search(r"\bbuy\s+and\s+hold\b", prompt, flags=re.IGNORECASE):
            assumptions.append(
                f"Interpreted buy-and-hold language as a core {tradable_symbol} sleeve."
            )
        else:
            assumptions.append(
                f"Interpreted core language as a core {tradable_symbol} sleeve."
            )

        if core_allocation_pct is None and overlay_allocation_pct is None:
            core_allocation_pct = 0.60
            assumptions.append("Used 60% core and 40% tactical overlay by default.")
        elif overlay_allocation_pct is not None:
            assumptions.append(
                f"Used explicit {core_allocation_pct * 100:g}% core and "
                f"{overlay_allocation_pct * 100:g}% tactical overlay allocation."
            )
        elif core_allocation_pct is not None:
            assumptions.append(
                f"Used explicit {core_allocation_pct * 100:g}% core allocation."
            )

        core_overlay_enabled = True
        position_management_removed = False
        if scale_in_fraction_edit is None and scale_out_fraction_edit is None:
            assumptions.append("Used 25% scale-in and 50% scale-out by default.")
        if scale_in_fraction_edit is None:
            scale_in_fraction_edit = 0.25
        if scale_out_fraction_edit is None:
            scale_out_fraction_edit = 0.50
        has_position_management_edit = True

    base_config = current_config if has_current_config else {}

    if has_current_config:
        assumptions.append("Used current_config as the base draft for version generation.")

    default_config = dict(base_config) if has_current_config else {}

    if not has_current_config:
        default_config = _build_create_flow_default_config(
            tradable_symbol=tradable_symbol,
            benchmark_symbol=benchmark_symbol,
            reference_symbols=reference_symbols,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            transaction_cost_bps_edit=transaction_cost_bps_edit,
            allocation_value=allocation_value,
            max_position_pct_edit=max_position_pct_edit,
            overlay_allocation_pct=overlay_allocation_pct,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
            core_overlay_enabled=core_overlay_enabled,
            core_overlay_disabled=core_overlay_disabled,
            core_allocation_pct=core_allocation_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            partial_take_profit=partial_take_profit,
            cooldown_bars=cooldown_bars,
            position_management_removed=position_management_removed,
            scale_in_fraction_edit=scale_in_fraction_edit,
            scale_out_fraction_edit=scale_out_fraction_edit,
            profit_reduce_threshold_edit=profit_reduce_threshold_edit,
            assumptions=assumptions,
        )
    else:
        default_config = _build_update_flow_default_config(
            base_config=base_config,
            tradable_symbol=tradable_symbol,
            benchmark_symbol=benchmark_symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            allocation_value=allocation_value,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
            explicit_date_edits=explicit_date_edits,
        )

        default_config = _apply_update_flow_edits(
            default_config=default_config,
            has_current_config=has_current_config,
            base_config=base_config,
            prompt=prompt,
            prompt_lower=prompt_lower,
            tradable_symbol=tradable_symbol,
            benchmark_symbol=benchmark_symbol,
            tradable_symbol_edit=tradable_symbol_edit,
            initial_capital=initial_capital,
            allocation_value=allocation_value,
            allocation_edit_value=allocation_edit_value,
            max_position_pct_edit=max_position_pct_edit,
            overlay_allocation_pct=overlay_allocation_pct,
            transaction_cost_bps_edit=transaction_cost_bps_edit,
            stop_loss_removed=stop_loss_removed,
            stop_loss_pct=stop_loss_pct,
            take_profit_removed=take_profit_removed,
            take_profit_pct=take_profit_pct,
            cooldown_removed=cooldown_removed,
            cooldown_edit=cooldown_edit,
            cooldown_bars=cooldown_bars,
            partial_take_profit_removed=partial_take_profit_removed,
            partial_take_profit=partial_take_profit,
            scale_in_fraction_edit=scale_in_fraction_edit,
            scale_out_fraction_edit=scale_out_fraction_edit,
            profit_reduce_threshold_edit=profit_reduce_threshold_edit,
            position_management_removed=position_management_removed,
            has_position_management_edit=has_position_management_edit,
            core_overlay_enabled=core_overlay_enabled,
            core_overlay_disabled=core_overlay_disabled,
            core_allocation_pct=core_allocation_pct,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
            rsi_entry_threshold_edit=rsi_entry_threshold_edit,
            rsi_exit_threshold_edit=rsi_exit_threshold_edit,
            rsi_entry_lookback_edit=rsi_entry_lookback_edit,
            rsi_exit_lookback_edit=rsi_exit_lookback_edit,
            entry_fast_window_edit=entry_fast_window_edit,
            entry_slow_window_edit=entry_slow_window_edit,
            exit_fast_window_edit=exit_fast_window_edit,
            exit_slow_window_edit=exit_slow_window_edit,
            has_partial_sma_window_edit=has_partial_sma_window_edit,
            month_values=month_values,
            seasonality_month_edit_action=seasonality_month_edit_action,
            has_seasonality_month_edit=has_seasonality_month_edit,
            has_partial_relative_strength_edit=has_partial_relative_strength_edit,
            relative_strength_reference_symbol_edit=relative_strength_reference_symbol_edit,
            relative_strength_lookback_edit=relative_strength_lookback_edit,
            relative_strength_threshold_edit=relative_strength_threshold_edit,
            confirmation_family=confirmation_family,
            add_confirmation_intent=add_confirmation_intent,
            remove_confirmation_intent=remove_confirmation_intent,
            has_confirmation_edit_intent=has_confirmation_edit_intent,
            confirmation_rules=confirmation_rules,
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
            has_temporal_rule_edit_intent=has_temporal_rule_edit_intent,
            entry_group_operator_edit=entry_group_operator_edit,
            exit_group_operator_edit=exit_group_operator_edit,
            entry_group_first_condition_edit=entry_group_first_condition_edit,
            entry_group_second_condition_edit=entry_group_second_condition_edit,
            exit_group_first_condition_edit=exit_group_first_condition_edit,
            exit_group_second_condition_edit=exit_group_second_condition_edit,
            entry_window_inner_rule_edit=entry_window_inner_rule_edit,
            exit_window_inner_rule_edit=exit_window_inner_rule_edit,
            has_nested_composite_edit_intent=has_nested_composite_edit_intent,
            entry_not_inner_rule_edit=entry_not_inner_rule_edit,
            exit_not_inner_rule_edit=exit_not_inner_rule_edit,
            has_not_rule_edit_intent=has_not_rule_edit_intent,
            remove_entry_group_first_condition=remove_entry_group_first_condition,
            remove_entry_group_second_condition=remove_entry_group_second_condition,
            remove_exit_group_first_condition=remove_exit_group_first_condition,
            remove_exit_group_second_condition=remove_exit_group_second_condition,
            remove_entry_window_wrapper=remove_entry_window_wrapper,
            remove_exit_window_wrapper=remove_exit_window_wrapper,
            remove_entry_not_wrapper=remove_entry_not_wrapper,
            remove_exit_not_wrapper=remove_exit_not_wrapper,
            remove_entry_sequence_first_step=remove_entry_sequence_first_step,
            remove_entry_sequence_second_step=remove_entry_sequence_second_step,
            remove_exit_sequence_first_step=remove_exit_sequence_first_step,
            remove_exit_sequence_second_step=remove_exit_sequence_second_step,
            has_nested_composite_removal_intent=has_nested_composite_removal_intent,
            assumptions=assumptions,
        )

    config = _sync_reference_symbols(_merge_dict(base_config, default_config))

    if add_reduce_reference_series_setup is not None:
        config["name"] = _build_add_reduce_strategy_name(
            tradable_symbol=config.get("tradable_symbol", tradable_symbol),
            setup=add_reduce_reference_series_setup,
        )
        if max_position_pct_edit is None:
            allocation = dict(config.get("allocation") or {})
            allocation["max_position_pct"] = 1.0
            config["allocation"] = allocation

    summary = _build_strategy_summary(
        config=config,
        tradable_symbol=tradable_symbol,
        benchmark_symbol=benchmark_symbol,
        start_date=start_date,
        end_date=end_date,
        has_current_config=has_current_config,
        assumptions=assumptions,
        transaction_cost_bps_edit=transaction_cost_bps_edit,
        allocation_edit_value=allocation_edit_value,
        max_position_pct_edit=max_position_pct_edit,
        stop_loss_removed=stop_loss_removed,
        stop_loss_pct=stop_loss_pct,
        take_profit_removed=take_profit_removed,
        take_profit_pct=take_profit_pct,
        cooldown_removed=cooldown_removed,
        cooldown_edit=cooldown_edit,
        cooldown_bars=cooldown_bars,
        partial_take_profit_removed=partial_take_profit_removed,
        partial_take_profit=partial_take_profit,
        position_management_removed=position_management_removed,
        has_position_management_edit=has_position_management_edit,
        core_overlay_disabled=core_overlay_disabled,
        core_overlay_enabled=core_overlay_enabled,
    )

    validated = StrategyV2.model_validate(config)
    validated_config = validated.model_dump(mode="json", exclude_none=True)
    changes = _summarize_changes(base_config, validated_config)

    return (
        validated_config,
        summary,
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


_NUMBER_TOKEN = r"\d+(?:\.\d+)?%?"

_SWEEP_PATH_SPECS = [
    (
        "entry_rule.series_threshold",
        [
            r"vix\s+add\s+thresholds?",
            r"add\s+vix\s+thresholds?",
            r"add\s+thresholds?",
            (
                r"add\s+when\s+vix\s+(?:is\s+)?"
                r"(?:below|under|less\s+than|lower\s+than|<)"
            ),
            r"vix\s+(?:is\s+)?(?:below|under|less\s+than|lower\s+than|<)",
            r"vix\s+thresholds?",
        ],
        False,
    ),
    (
        "exit_rule.series_threshold",
        [
            r"vix\s+reduce\s+thresholds?",
            r"reduce\s+vix\s+thresholds?",
            r"(?:reduce|trim)\s+thresholds?",
            (
                r"(?:reduce|trim)\s+when\s+vix\s+(?:is\s+)?"
                r"(?:above|over|greater\s+than|higher\s+than|>)"
            ),
            r"vix\s+(?:is\s+)?(?:above|over|greater\s+than|higher\s+than|>)",
        ],
        False,
    ),
    (
        "entry_rule.threshold",
        [
            r"(?:entry\s+rsi|rsi\s+entry)\s+thresholds?",
            r"rsi\s+buy\s+thresholds?",
            r"(?:buy|entry)\s+(?:rsi\s+)?thresholds?",
            r"entry\s+thresholds?",
            r"entry\s+rsi",
            r"rsi\s+entry",
            r"rsi\s+buy",
            r"rsi\s+thresholds?",
        ],
        False,
    ),
    (
        "exit_rule.threshold",
        [
            r"(?:exit\s+rsi|rsi\s+exit)\s+thresholds?",
            r"rsi\s+sell\s+thresholds?",
            r"(?:sell|exit)\s+(?:rsi\s+)?thresholds?",
            r"exit\s+thresholds?",
            r"exit\s+rsi",
            r"rsi\s+exit",
            r"rsi\s+sell",
        ],
        False,
    ),
    (
        "entry_rule.fast_window",
        [
            r"entry\s+(?:rule\s+)?fast\s+windows?",
            r"(?:sma\s+)?fast\s+windows?",
            r"sma\s+windows?",
        ],
        False,
    ),
    (
        "entry_rule.slow_window",
        [
            r"entry\s+(?:rule\s+)?slow\s+windows?",
            r"(?:sma\s+)?slow\s+windows?",
        ],
        False,
    ),
    (
        "exit_rule.fast_window",
        [r"exit\s+(?:rule\s+)?fast\s+windows?"],
        False,
    ),
    (
        "exit_rule.slow_window",
        [r"exit\s+(?:rule\s+)?slow\s+windows?"],
        False,
    ),
    (
        "risk.stop_loss_pct",
        [r"stop\s+loss(?:\s+pct|\s+percent|\s+percentages?)?"],
        True,
    ),
    (
        "risk.take_profit_pct",
        [r"take\s+profit(?:\s+pct|\s+percent|\s+percentages?)?"],
        True,
    ),
    (
        "risk.cooldown_bars",
        [r"cooldown(?:\s+bars?)?"],
        False,
    ),
    (
        "core_overlay.core_allocation_pct",
        [
            r"core\s+allocations?",
            r"core\s+allocation(?:\s+pct|\s+percent|\s+percentages?)?",
        ],
        True,
    ),
    (
        "position_management.scale_in_fraction",
        [
            r"scale[-\s]+in(?:\s+fractions?|\s+pct|\s+percent|\s+percentages?)?",
            r"overlay\s+sizing\s+with\s+scale\s+in",
        ],
        True,
    ),
    (
        "position_management.scale_out_fraction",
        [
            r"scale[-\s]+out(?:\s+fractions?|\s+pct|\s+percent|\s+percentages?)?",
        ],
        True,
    ),
]


def _format_grid_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_grid_values(values: list[Any]) -> str:
    return ", ".join(_format_grid_value(value) for value in values)


def _normalize_sweep_number(token: str, *, percent: bool) -> int | float:
    cleaned = token.strip().rstrip("%")
    value = float(cleaned)
    if percent:
        value = value / 100.0 if token.strip().endswith("%") or value > 1 else value
    if value.is_integer() and not percent:
        return int(value)
    return value


def _range_values(start: int | float, end: int | float, step: int | float | None) -> list[int | float]:
    if step is None:
        distance = abs(float(end) - float(start))
        step = 5 if distance >= 10 else max(1, distance / 2)
    if step <= 0:
        return [start, end]

    values: list[int | float] = []
    current = float(start)
    end_value = float(end)
    direction = 1 if end_value >= current else -1
    step_value = abs(float(step)) * direction

    while (direction == 1 and current <= end_value) or (direction == -1 and current >= end_value):
        values.append(int(current) if current.is_integer() else round(current, 6))
        current += step_value

    if values[-1] != end:
        values.append(end)
    return values


def _extract_sweep_values(
    text: str,
    label_patterns: list[str],
    *,
    percent: bool = False,
) -> list[Any] | None:
    for label in label_patterns:
        range_pattern = (
            rf"{label}\s+from\s+({_NUMBER_TOKEN})\s+to\s+({_NUMBER_TOKEN})"
            rf"(?:\s+by\s+({_NUMBER_TOKEN}))?"
        )
        range_match = re.search(range_pattern, text, flags=re.IGNORECASE)
        if range_match:
            start = _normalize_sweep_number(range_match.group(1), percent=False)
            end = _normalize_sweep_number(range_match.group(2), percent=False)
            step = (
                _normalize_sweep_number(range_match.group(3), percent=False)
                if range_match.group(3)
                else None
            )
            values = _range_values(start, end, step)
            return [
                _normalize_sweep_number(f"{value}%", percent=True) if percent else value
                for value in values
            ]

        compact_range_pattern = (
            rf"{label}\s+({_NUMBER_TOKEN})\s+to\s+({_NUMBER_TOKEN})"
            rf"(?:\s+by\s+({_NUMBER_TOKEN}))?"
        )
        compact_range_match = re.search(compact_range_pattern, text, flags=re.IGNORECASE)
        if compact_range_match:
            start = _normalize_sweep_number(compact_range_match.group(1), percent=False)
            end = _normalize_sweep_number(compact_range_match.group(2), percent=False)
            step = (
                _normalize_sweep_number(compact_range_match.group(3), percent=False)
                if compact_range_match.group(3)
                else None
            )
            values = _range_values(start, end, step)
            return [
                _normalize_sweep_number(f"{value}%", percent=True) if percent else value
                for value in values
            ]

        list_pattern = (
            rf"{label}(?:\s+(?:of|at|to|=|:))?\s+"
            rf"(?P<values>{_NUMBER_TOKEN}(?:\s*(?:,|/|\band\b)\s*{_NUMBER_TOKEN})+)"
        )
        list_match = re.search(list_pattern, text, flags=re.IGNORECASE)
        if list_match:
            tokens = re.findall(_NUMBER_TOKEN, list_match.group("values"))
            return [_normalize_sweep_number(token, percent=percent) for token in tokens]

    return None


def _extract_parameter_sweep_grid(prompt: str) -> dict[str, list[Any]]:
    grid: dict[str, list[Any]] = {}

    for path, labels, percent in _SWEEP_PATH_SPECS:
        values = _extract_sweep_values(prompt, labels, percent=percent)
        if values is not None:
            grid[path] = values

    return grid


def _extract_single_sweep_value(
    text: str,
    label_patterns: list[str],
    *,
    percent: bool,
) -> Any | None:
    for label in label_patterns:
        match = re.search(
            rf"{label}(?:\s+(?:of|at|to|=|:))?\s+({_NUMBER_TOKEN})\b",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return _normalize_sweep_number(match.group(1), percent=percent)
    return None


def _extract_sweep_grid_additions(prompt: str) -> dict[str, list[Any]]:
    if not re.search(r"\b(add|include)\b", prompt, flags=re.IGNORECASE):
        return {}

    additions: dict[str, list[Any]] = {}
    for path, labels, percent in _SWEEP_PATH_SPECS:
        value = _extract_single_sweep_value(prompt, labels, percent=percent)
        if value is not None:
            additions[path] = [value]
    return additions


def _looks_like_parameter_sweep_prompt(prompt: str) -> bool:
    text = prompt.lower()
    grid = _extract_parameter_sweep_grid(prompt)
    if not grid:
        return False

    return bool(
        re.search(r"\b(test|try|sweep|compare|rank|optimi[sz]e)\b", text)
        or re.search(r"\b(thresholds|windows|values|levels)\b", text)
    )


def _extract_sweep_ranking_metric(prompt: str) -> str:
    match = re.search(
        r"rank(?:ed|ing)?\s+by\s+([a-z_ ]+?)(?:[.!,;]|$)",
        prompt,
        flags=re.IGNORECASE,
    )
    if not match:
        return normalize_ranking_metric(None)

    metric = match.group(1).strip().lower().replace(" ", "_")
    return normalize_ranking_metric(metric)


def _build_parameter_sweep_title(base_config: dict[str, Any], grid: dict[str, list[Any]]) -> str:
    symbol = str(base_config.get("tradable_symbol") or "ETF")
    threshold_paths = [
        path
        for path in grid
        if path.endswith(".threshold")
        or path in {"entry_rule.threshold", "exit_rule.threshold"}
    ]
    if any(_is_reference_threshold_sweep_path(base_config, path) for path in threshold_paths):
        return f"{symbol} VIX Threshold Sweep"
    if threshold_paths:
        return f"{symbol} RSI Threshold Sweep"
    if any(path.endswith("_window") for path in grid):
        return f"{symbol} SMA Window Sweep"
    if any(path.startswith(("core_overlay.", "position_management.")) for path in grid):
        return f"{symbol} Sizing Sweep"
    return f"{symbol} Parameter Sweep"


def _is_reference_threshold_sweep_path(base_config: dict[str, Any], path: str) -> bool:
    if not path.endswith(".threshold"):
        return False
    try:
        rule = get_nested(base_config, path.rsplit(".", 1)[0])
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return _is_reference_series_threshold_rule(rule)


def _build_parameter_sweep_summary(
    *,
    base_config: dict[str, Any],
    grid: dict[str, list[Any]],
    ranking_metric: str,
    count: int,
) -> str:
    symbol = str(base_config.get("tradable_symbol") or "ETF")
    start_date = str(base_config.get("start_date") or "the start date")
    end_date = str(base_config.get("end_date") or "the end date")
    grid_summary = "; ".join(
        f"{path}: {_format_grid_values(values)}" for path, values in grid.items()
    )
    return (
        f"Parameter sweep draft for {symbol} from {start_date} to {end_date}. "
        f"It will test {count} variants, rank by {ranking_metric}, and vary {grid_summary}."
    )


def _current_sweep_draft_from_context(
    req: StrategyBuilderGenerateRequest,
) -> dict[str, Any] | None:
    current_config = req.context.current_config if req.context else None
    if not isinstance(current_config, dict):
        return None

    if isinstance(current_config.get("sweep_draft"), dict):
        current_config = current_config["sweep_draft"]

    if isinstance(current_config.get("base_config"), dict) and isinstance(current_config.get("grid"), dict):
        return current_config

    return None


def _parameter_path_guidance(base_config: dict[str, Any], path: str) -> str | None:
    entry_rule = base_config.get("entry_rule")
    exit_rule = base_config.get("exit_rule")

    if path == "entry_rule.threshold" and not (
        _has_rsi_rule(entry_rule, rule_type="rsi_below")
        or _has_rsi_rule(entry_rule, rule_type="rsi_above")
        or _has_reference_series_threshold_rule(entry_rule)
    ):
        return (
            "This draft does not use RSI rules yet. You can create an RSI strategy first, "
            "or ask me to replace the entry/exit rules with RSI."
        )

    if path == "exit_rule.threshold" and not (
        _has_rsi_rule(exit_rule, rule_type="rsi_below")
        or _has_rsi_rule(exit_rule, rule_type="rsi_above")
        or _has_reference_series_threshold_rule(exit_rule)
    ):
        return (
            "This draft does not use RSI rules yet. You can create an RSI strategy first, "
            "or ask me to replace the entry/exit rules with RSI."
        )

    if path.startswith("entry_rule.") and path.endswith("_window") and not _has_moving_average_rule(entry_rule):
        return (
            "This draft does not use SMA rules yet. You can create an SMA strategy first, "
            "or ask me to replace the entry/exit rules with SMA."
        )

    if path.startswith("exit_rule.") and path.endswith("_window") and not _has_moving_average_rule(exit_rule):
        return (
            "This draft does not use SMA rules yet. You can create an SMA strategy first, "
            "or ask me to replace the entry/exit rules with SMA."
        )

    if path == "core_overlay.core_allocation_pct" and not isinstance(
        base_config.get("core_overlay"), dict
    ):
        return (
            "This draft does not have core allocation settings yet. "
            "Enable core allocation first, then I can sweep the core allocation values."
        )

    if path.startswith("position_management.") and not isinstance(
        base_config.get("position_management"), dict
    ):
        return (
            "This draft does not have add/reduce sizing settings yet. "
            "Enable position management first, then I can sweep scale-in or scale-out values."
        )

    return None


def _has_reference_series_threshold_rule(rule: Any, *, symbol: str | None = None) -> bool:
    if not isinstance(rule, dict):
        return False

    kind = rule.get("kind")
    if kind == "atomic":
        if rule.get("type") not in {"series_below", "series_above"}:
            return False
        if (
            symbol is not None
            and str(rule.get("symbol") or "").upper() != symbol.upper()
        ):
            return False
        return isinstance(rule.get("threshold"), (int, float)) and not isinstance(
            rule.get("threshold"), bool
        )

    if kind == "not":
        return _has_reference_series_threshold_rule(rule.get("rule"), symbol=symbol)

    if kind == "group":
        return any(
            _has_reference_series_threshold_rule(child_rule, symbol=symbol)
            for child_rule in rule.get("rules", [])
        )

    if kind == "window":
        return _has_reference_series_threshold_rule(rule.get("rule"), symbol=symbol)

    if kind == "sequence":
        return any(
            _has_reference_series_threshold_rule(step, symbol=symbol)
            for step in rule.get("steps", [])
        )

    return False


def _collect_rule_parameter_paths(
    rule: Any,
    *,
    root_path: str,
    attribute: str,
    family: str,
    symbol: str | None = None,
) -> list[str]:
    if not isinstance(rule, dict):
        return []

    kind = rule.get("kind")

    if kind == "atomic":
        rule_type = rule.get("type")
        if family == "rsi" and rule_type not in {"rsi_below", "rsi_above"}:
            return []
        if family == "sma" and rule_type not in {
            "sma_cross_above",
            "sma_cross_below",
            "sma_above",
        }:
            return []
        if family == "reference_series":
            if rule_type not in {"series_below", "series_above"}:
                return []
            if (
                symbol is not None
                and str(rule.get("symbol") or "").upper() != symbol.upper()
            ):
                return []
        if attribute not in rule:
            return []
        return [f"{root_path}.{attribute}"]

    if kind == "not":
        return _collect_rule_parameter_paths(
            rule.get("rule"),
            root_path=f"{root_path}.rule",
            attribute=attribute,
            family=family,
            symbol=symbol,
        )

    if kind == "group":
        paths: list[str] = []
        for index, child_rule in enumerate(rule.get("rules", [])):
            paths.extend(
                _collect_rule_parameter_paths(
                    child_rule,
                    root_path=f"{root_path}.rules[{index}]",
                    attribute=attribute,
                    family=family,
                    symbol=symbol,
                )
            )
        return paths

    if kind == "window":
        return _collect_rule_parameter_paths(
            rule.get("rule"),
            root_path=f"{root_path}.rule",
            attribute=attribute,
            family=family,
            symbol=symbol,
        )

    if kind == "sequence":
        paths: list[str] = []
        for index, step in enumerate(rule.get("steps", [])):
            paths.extend(
                _collect_rule_parameter_paths(
                    step,
                    root_path=f"{root_path}.steps[{index}]",
                    attribute=attribute,
                    family=family,
                    symbol=symbol,
                )
            )
        return paths

    return []


def _has_sweep_side_word(prompt: str, side: str) -> bool:
    if side == "entry":
        return bool(
            re.search(
                r"\b(entry|buy|buying|add|adding)\b",
                prompt,
                flags=re.IGNORECASE,
            )
        )
    return bool(
        re.search(
            r"\b(exit|sell|selling|reduce|reducing|trim|trimming)\b",
            prompt,
            flags=re.IGNORECASE,
        )
    )


def _has_sweep_family_word(prompt: str, family: str) -> bool:
    if family == "rsi":
        return bool(re.search(r"\brsi\b", prompt, flags=re.IGNORECASE))
    if family == "sma":
        return bool(re.search(r"\b(sma|moving\s+average)\b", prompt, flags=re.IGNORECASE))
    if family == "reference_series":
        return bool(re.search(r"\bvix\b", prompt, flags=re.IGNORECASE))
    return False


def _has_generic_sma_window_intent(prompt: str) -> bool:
    return bool(
        re.search(
            r"\b(?:sma|moving\s+average)\s+(?:lookbacks?|windows?)\b",
            prompt,
            flags=re.IGNORECASE,
        )
        and not re.search(r"\b(fast|slow)\s+windows?\b", prompt, flags=re.IGNORECASE)
    )


def _root_key_for_sweep_path(path: str) -> str | None:
    if path.startswith("entry_rule."):
        return "entry_rule"
    if path.startswith("exit_rule."):
        return "exit_rule"
    return None


def _path_conflicts_with_explicit_sweep_side(prompt: str, path: str, family: str) -> bool:
    if not _has_sweep_family_word(prompt, family):
        return False

    root_key = _root_key_for_sweep_path(path)
    if root_key == "entry_rule":
        return _has_sweep_side_word(prompt, "exit") and not _has_sweep_side_word(prompt, "entry")
    if root_key == "exit_rule":
        return _has_sweep_side_word(prompt, "entry") and not _has_sweep_side_word(prompt, "exit")
    return False


def _explicit_sweep_root_for_conflicting_path(prompt: str, path: str, family: str) -> str | None:
    if not _path_conflicts_with_explicit_sweep_side(prompt, path, family):
        return None
    if _has_sweep_side_word(prompt, "entry"):
        return "entry_rule"
    if _has_sweep_side_word(prompt, "exit"):
        return "exit_rule"
    return None


def _resolve_semantic_sweep_target(
    *,
    base_config: dict[str, Any],
    prompt: str,
    path: str,
    root_key: str,
    attribute: str,
    family: str,
    label: str,
    strict_ambiguity: bool,
    symbol: str | None = None,
) -> tuple[str | None, str | None]:
    requested_root = _root_key_for_sweep_path(path) or root_key
    prompt_has_requested_side = _has_sweep_side_word(
        prompt,
        "entry" if requested_root == "entry_rule" else "exit",
    )
    prompt_has_any_side = _has_sweep_side_word(prompt, "entry") or _has_sweep_side_word(
        prompt, "exit"
    )
    prompt_has_family = _has_sweep_family_word(prompt, family)

    search_roots = [requested_root]
    if (
        strict_ambiguity
        and prompt_has_family
        and not prompt_has_requested_side
        and not prompt_has_any_side
    ):
        search_roots = ["entry_rule", "exit_rule"]

    if family == "sma" and attribute == "fast_window" and _has_generic_sma_window_intent(prompt):
        attribute = "slow_window"
        label = label.replace("fast window", "window").replace("slow window", "window")

    matches: list[str] = []
    for search_root in search_roots:
        matches.extend(
            _collect_rule_parameter_paths(
                base_config.get(search_root),
                root_path=search_root,
                attribute=attribute,
                family=family,
                symbol=symbol,
            )
        )

    if len(matches) == 1:
        return matches[0], None

    if len(matches) > 1:
        return None, (
            f"This draft has multiple possible {label} targets. "
            "Please specify whether you mean the entry/buy rule or the exit/sell rule."
        )

    guidance_path = f"{requested_root}.{attribute}"
    guidance = _parameter_path_guidance(base_config, guidance_path)
    if guidance is not None:
        return None, guidance
    return None, (
        f"I could not find a matching {label} in the current draft. "
        "Please choose a parameter that already exists in the strategy rules."
    )


def _resolve_legacy_sweep_path(
    base_config: dict[str, Any],
    path: str,
    *,
    prompt: str,
    strict_ambiguity: bool,
) -> tuple[str | None, str | None]:
    legacy_specs = {
        "entry_rule.threshold": ("entry_rule", "threshold", "rsi", "entry RSI threshold"),
        "exit_rule.threshold": ("exit_rule", "threshold", "rsi", "exit RSI threshold"),
        "entry_rule.series_threshold": (
            "entry_rule",
            "threshold",
            "reference_series",
            "entry VIX threshold",
        ),
        "exit_rule.series_threshold": (
            "exit_rule",
            "threshold",
            "reference_series",
            "exit VIX threshold",
        ),
        "entry_rule.fast_window": (
            "entry_rule",
            "fast_window",
            "sma",
            "entry SMA fast window",
        ),
        "entry_rule.slow_window": (
            "entry_rule",
            "slow_window",
            "sma",
            "entry SMA slow window",
        ),
        "exit_rule.fast_window": (
            "exit_rule",
            "fast_window",
            "sma",
            "exit SMA fast window",
        ),
        "exit_rule.slow_window": (
            "exit_rule",
            "slow_window",
            "sma",
            "exit SMA slow window",
        ),
    }
    spec = legacy_specs.get(path)
    if spec is None:
        return path, None

    root_key, attribute, family, label = spec
    symbol = "VIX" if family == "reference_series" else None
    explicit_root = (
        _explicit_sweep_root_for_conflicting_path(prompt, path, family)
        if strict_ambiguity
        else None
    )
    if explicit_root is not None:
        return _resolve_semantic_sweep_target(
            base_config=base_config,
            prompt=prompt,
            path=f"{explicit_root}.{attribute}",
            root_key=explicit_root,
            attribute=attribute,
            family=family,
            label=label,
            strict_ambiguity=strict_ambiguity,
            symbol=symbol,
        )

    rule = base_config.get(root_key)
    if (
        isinstance(rule, dict)
        and rule.get("kind") == "atomic"
        and (
            family != "reference_series"
            or (
                rule.get("type") in {"series_below", "series_above"}
                and str(rule.get("symbol") or "").upper() == "VIX"
            )
        )
    ):
        if (
            family == "sma"
            and attribute == "fast_window"
            and _has_generic_sma_window_intent(prompt)
        ) or (
            strict_ambiguity
            and _has_sweep_family_word(prompt, family)
            and not _has_sweep_side_word(prompt, "entry")
            and not _has_sweep_side_word(prompt, "exit")
        ):
            return _resolve_semantic_sweep_target(
                base_config=base_config,
                prompt=prompt,
                path=path,
                root_key=root_key,
                attribute=attribute,
                family=family,
                label=label,
                strict_ambiguity=strict_ambiguity,
                symbol=symbol,
            )
        if path.endswith(".series_threshold"):
            return f"{root_key}.{attribute}", None
        return path, None

    return _resolve_semantic_sweep_target(
        base_config=base_config,
        prompt=prompt,
        path=path,
        root_key=root_key,
        attribute=attribute,
        family=family,
        label=label,
        strict_ambiguity=strict_ambiguity,
        symbol=symbol,
    )


def _prefer_entry_group_for_vix_rsi_sweep(
    *,
    base_config: dict[str, Any],
    grid: dict[str, list[Any]],
    prompt: str,
) -> bool:
    entry_rule = base_config.get("entry_rule")
    return (
        isinstance(entry_rule, dict)
        and entry_rule.get("kind") == "group"
        and entry_rule.get("operator") == "AND"
        and "entry_rule.series_threshold" in grid
        and "entry_rule.threshold" in grid
        and _has_sweep_family_word(prompt, "reference_series")
        and _has_sweep_family_word(prompt, "rsi")
        and _has_reference_series_threshold_rule(entry_rule, symbol="VIX")
        and _has_rsi_rule(entry_rule, rule_type="rsi_below")
    )


def _has_explicit_vix_sweep_direction(prompt: str, path: str) -> bool:
    if path == "entry_rule.series_threshold":
        return bool(
            re.search(
                (
                    r"\b(?:vix\s+(?:is\s+)?"
                    r"(?:below|under|less\s+than|lower\s+than|<)|"
                    r"add(?:\s+when)?\s+vix)"
                ),
                prompt,
                flags=re.IGNORECASE,
            )
        )
    if path == "exit_rule.series_threshold":
        return bool(
            re.search(
                (
                    r"\b(?:vix\s+(?:is\s+)?"
                    r"(?:above|over|greater\s+than|higher\s+than|>)|"
                    r"(?:reduce|trim)(?:\s+when)?\s+vix)"
                ),
                prompt,
                flags=re.IGNORECASE,
            )
        )
    return False


def _resolve_follow_up_sweep_grid_paths(
    *,
    base_config: dict[str, Any],
    grid: dict[str, list[Any]],
    prompt: str,
    max_backtest_years: int,
    strict_ambiguity: bool,
) -> tuple[dict[str, list[Any]] | None, dict[str, Any] | None]:
    resolved_grid: dict[str, list[Any]] = {}
    prefer_entry_group = _prefer_entry_group_for_vix_rsi_sweep(
        base_config=base_config,
        grid=grid,
        prompt=prompt,
    )

    for path, values in grid.items():
        path_strict_ambiguity = strict_ambiguity
        if prefer_entry_group and path in {
            "entry_rule.series_threshold",
            "entry_rule.threshold",
        }:
            path_strict_ambiguity = False
        if _has_explicit_vix_sweep_direction(prompt, path):
            path_strict_ambiguity = False
        resolved_path, guidance = _resolve_legacy_sweep_path(
            base_config,
            path,
            prompt=prompt,
            strict_ambiguity=path_strict_ambiguity,
        )
        if guidance is not None:
            return None, _build_response(
                response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
                message=guidance,
                validation_data=build_validation_data(
                    message=guidance,
                    max_backtest_years=max_backtest_years,
                ),
                guidance_data=_build_guidance_data(
                    guidance_type=StrategyBuilderGuidanceType.UNSUPPORTED_EDIT_TARGET,
                ),
            )
        if resolved_path is not None:
            resolved_grid[resolved_path] = values

    return resolved_grid, None


def _validate_follow_up_sweep_grid(
    *,
    base_config: dict[str, Any],
    grid: dict[str, list[Any]],
    max_backtest_years: int,
) -> dict[str, Any] | None:
    for path in grid:
        guidance = _parameter_path_guidance(base_config, path)
        if guidance is not None:
            return _build_response(
                response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
                message=guidance,
                validation_data=build_validation_data(
                    message=guidance,
                    max_backtest_years=max_backtest_years,
                ),
                guidance_data=_build_guidance_data(
                    guidance_type=StrategyBuilderGuidanceType.UNSUPPORTED_EDIT_TARGET,
                ),
            )
    return None


def _build_parameter_sweep_response(
    *,
    base_config: dict[str, Any],
    grid: dict[str, list[Any]],
    ranking_metric: str,
    max_variants: int,
    max_backtest_years: int,
    prompt: str,
    strict_ambiguity: bool,
    warnings: list[str] | None = None,
    assumptions: list[str] | None = None,
) -> dict[str, Any]:
    grid, path_guidance_response = _resolve_follow_up_sweep_grid_paths(
        base_config=base_config,
        grid=grid,
        prompt=prompt,
        max_backtest_years=max_backtest_years,
        strict_ambiguity=strict_ambiguity,
    )
    if path_guidance_response is not None:
        return path_guidance_response
    if grid is None:
        grid = {}

    count = variant_count(grid)
    if count > max_variants:
        message = (
            f"This sweep would create {count} variants, but your plan allows up to "
            f"{max_variants}."
        )
        return _build_response(
            response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
            message=message,
            validation_data=build_validation_data(
                message=message,
                max_backtest_years=max_backtest_years,
            ),
        )

    guidance_response = _validate_follow_up_sweep_grid(
        base_config=base_config,
        grid=grid,
        max_backtest_years=max_backtest_years,
    )
    if guidance_response is not None:
        return guidance_response

    try:
        sweep_request = build_sweep_request(
            {
                "base_config": base_config,
                "grid": grid,
                "ranking_metric": ranking_metric,
                "max_variants": max_variants,
            }
        )
    except ParameterSweepError as exc:
        message = str(exc)
        return _build_response(
            response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
            message=message,
            validation_data=build_validation_data(
                message=message,
                max_backtest_years=max_backtest_years,
            ),
        )

    title = _build_parameter_sweep_title(base_config, sweep_request["grid"])
    summary = _build_parameter_sweep_summary(
        base_config=base_config,
        grid=sweep_request["grid"],
        ranking_metric=sweep_request["ranking_metric"],
        count=sweep_request["variant_count"],
    )

    return _build_response(
        response_type=StrategyBuilderResponseType.PARAMETER_SWEEP_DRAFT,
        message=summary,
        summary=summary,
        warnings=warnings or [],
        assumptions=assumptions or [],
        sweep_draft={
            "title": title,
            "base_config": sweep_request["base_config"],
            "grid": sweep_request["grid"],
            "ranking_metric": sweep_request["ranking_metric"],
            "variant_count": sweep_request["variant_count"],
            "max_variants": sweep_request["max_variants"],
            "summary": summary,
        },
    )


def _extract_sweep_max_variants_edit(prompt: str) -> int | None:
    match = re.search(
        r"(?:change|set|use)?\s*max(?:imum)?\s+variants?\s+(?:to\s+)?(\d+)",
        prompt,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return int(match.group(1))


def _generate_existing_parameter_sweep_edit(
    req: StrategyBuilderGenerateRequest,
    *,
    max_backtest_years: int,
) -> dict[str, Any] | None:
    current_sweep = _current_sweep_draft_from_context(req)
    if current_sweep is None:
        return None

    base_config = current_sweep.get("base_config")
    current_grid = current_sweep.get("grid")
    if not isinstance(base_config, dict) or not isinstance(current_grid, dict):
        return None

    prompt = req.prompt.strip()
    if not (
        _looks_like_parameter_sweep_prompt(prompt)
        or re.search(r"\brank(?:ed|ing)?\s+by\b", prompt, flags=re.IGNORECASE)
        or re.search(r"\bmax(?:imum)?\s+variants?\b", prompt, flags=re.IGNORECASE)
        or re.search(r"\b(add|include)\b", prompt, flags=re.IGNORECASE)
    ):
        return None

    parsed_grid = _extract_parameter_sweep_grid(prompt)
    additions = _extract_sweep_grid_additions(prompt)
    ranking_metric = (
        _extract_sweep_ranking_metric(prompt)
        if re.search(r"\brank(?:ed|ing)?\s+by\b", prompt, flags=re.IGNORECASE)
        else str(current_sweep.get("ranking_metric") or normalize_ranking_metric(None))
    )
    max_variants = _extract_sweep_max_variants_edit(prompt)
    if max_variants is None:
        existing_max_variants = current_sweep.get("max_variants", DEFAULT_MAX_VARIANTS)
        max_variants = existing_max_variants if isinstance(existing_max_variants, int) else DEFAULT_MAX_VARIANTS
    max_variants = min(max_variants, DEFAULT_MAX_VARIANTS)

    grid = {str(path): list(values) for path, values in current_grid.items() if isinstance(values, list)}

    if parsed_grid:
        for path, values in parsed_grid.items():
            grid[path] = values

    for path, values in additions.items():
        existing_values = grid.setdefault(path, [])
        for value in values:
            if value not in existing_values:
                existing_values.append(value)

    has_safe_change = bool(parsed_grid or additions or max_variants != current_sweep.get("max_variants")) or (
        ranking_metric != current_sweep.get("ranking_metric")
    )
    if not has_safe_change:
        message = (
            "I can make simple sweep edits like adding one grid value, changing the ranking metric, "
            "or changing max variants. For larger changes, start from the base strategy draft."
        )
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

    return _build_parameter_sweep_response(
        base_config=deepcopy(base_config),
        grid=grid,
        ranking_metric=ranking_metric,
        max_variants=max_variants,
        max_backtest_years=max_backtest_years,
        prompt=prompt,
        strict_ambiguity=True,
    )


def _generate_parameter_sweep_draft(
    req: StrategyBuilderGenerateRequest,
    *,
    max_backtest_years: int,
) -> dict[str, Any]:
    grid = _extract_parameter_sweep_grid(req.prompt)
    ranking_metric = _extract_sweep_ranking_metric(req.prompt)
    max_variants = DEFAULT_MAX_VARIANTS
    warnings: list[str] = []
    assumptions: list[str] = []

    current_config = req.context.current_config if req.context else None
    if isinstance(current_config, dict):
        base_config = deepcopy(current_config)
        if not isinstance(base_config.get("risk"), dict):
            base_config["risk"] = {}
        assumptions.append("Used the current Strategy V2 draft as the sweep base configuration.")
        strict_ambiguity = True
    else:
        base_config, _, warnings, assumptions, _ = generate_strategy_builder_draft(
            req,
            max_backtest_years=max_backtest_years,
        )
        strict_ambiguity = False

    return _build_parameter_sweep_response(
        base_config=base_config,
        grid=grid,
        ranking_metric=ranking_metric,
        max_variants=max_variants,
        max_backtest_years=max_backtest_years,
        prompt=req.prompt,
        strict_ambiguity=strict_ambiguity,
        warnings=warnings,
        assumptions=assumptions,
    )


def generate_strategy_builder_response(
    req: StrategyBuilderGenerateRequest,
    *,
    max_backtest_years: int = 5,
) -> dict[str, Any]:
    prompt = req.prompt.strip()
    has_current_config = _has_current_config(req)

    existing_sweep_edit = _generate_existing_parameter_sweep_edit(
        req,
        max_backtest_years=max_backtest_years,
    )
    if existing_sweep_edit is not None:
        return existing_sweep_edit

    if _looks_like_parameter_sweep_prompt(prompt):
        return _generate_parameter_sweep_draft(
            req,
            max_backtest_years=max_backtest_years,
        )

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
                if _should_attach_question_guidance(
                    prompt=prompt,
                    has_current_config=has_current_config,
                    answer_type=answer_data.get("answer_type"),
                )
                else None
            ),
        )

    if (
        _looks_like_unsupported_allocation_adjustment_prompt(prompt)
        and _extract_add_reduce_reference_series_setup(
            prompt,
            tradable_symbol="QQQ",
            benchmark_symbol="QQQ",
        )
        is None
    ):
        message = _UNSUPPORTED_ALLOCATION_ADJUSTMENT_MESSAGE
        return _build_response(
            response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
            message=message,
            validation_data=build_validation_data(
                message=message,
                max_backtest_years=max_backtest_years,
            ),
            guidance_data=_build_guidance_data(
                guidance_type=StrategyBuilderGuidanceType.GENERAL_GUIDANCE,
            ),
        )

    if not has_current_config and _requires_existing_draft_context(prompt):
        if "confirmation" in prompt.lower():
            message = (
                "Confirmation filters require an existing draft. "
                "Create a base ETF strategy first, then ask me to add or remove confirmation filters."
            )
        else:
            message = (
                "I need an existing draft before I can apply that edit. "
                "Create a base ETF strategy first, then ask me to modify it."
            )

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

    try:
        config, summary, warnings, assumptions, changes = generate_strategy_builder_draft(
            req,
            max_backtest_years=max_backtest_years,
        )
    except ValueError as exc:
        message = str(exc)
        if "could not convert string to float" in message:
            message = (
                "I could not parse one of the numeric values in that prompt. "
                "Please use explicit values like 60%, $100,000, or 5 bps."
            )
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
