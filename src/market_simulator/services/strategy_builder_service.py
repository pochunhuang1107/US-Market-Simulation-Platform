from __future__ import annotations

import re
from typing import Any

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderGenerateRequest,
    StrategyBuilderGuidanceType,
    StrategyBuilderResponseType,
)
from market_simulator.models.strategy_v2 import StrategyV2
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
    _extract_entry_slow_window_edit,
    _extract_exit_fast_window_edit,
    _extract_exit_slow_window_edit,
    _extract_explicit_date_edits,
    _extract_group_condition_edit,
    _extract_group_operator_edit,
    _extract_initial_capital,
    _extract_max_position_pct_edit,
    _extract_month_values,
    _extract_not_inner_rule_edit,
    _extract_partial_take_profit,
    _extract_percent,
    _extract_primary_symbol,
    _extract_profit_reduce_threshold_edit,
    _extract_reference_symbols,
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
    _is_supported_edit_request,
    _looks_like_edit_request,
    _looks_like_question,
)


def _has_current_config(req: StrategyBuilderGenerateRequest) -> bool:
    current_config = req.context.current_config if req.context else None
    return isinstance(current_config, dict) and bool(current_config)


def _merge_dict(base: dict, updates: dict) -> dict:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _build_create_flow_default_config(
    *,
    tradable_symbol: str,
    benchmark_symbol: str,
    reference_symbols: list[str],
    start_date,
    end_date,
    initial_capital: float,
    transaction_cost_bps_edit: float | None,
    allocation_value: float,
    max_position_pct_edit: float | None,
    entry_rule: dict,
    exit_rule: dict,
    core_overlay_enabled: bool,
    core_overlay_disabled: bool,
    core_allocation_pct: float | None,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    partial_take_profit: dict[str, Any] | None,
    cooldown_bars: int,
    position_management_removed: bool,
    scale_in_fraction_edit: float | None,
    scale_out_fraction_edit: float | None,
    profit_reduce_threshold_edit: float | None,
    assumptions: list[str],
) -> dict[str, Any]:
    default_config: dict[str, Any] = {}

    default_config["schema_version"] = "2.0"
    default_config["name"] = _build_strategy_name(tradable_symbol, entry_rule, exit_rule)
    default_config["tradable_symbol"] = tradable_symbol
    default_config["benchmark_symbol"] = benchmark_symbol
    default_config["reference_symbols"] = reference_symbols
    default_config["start_date"] = start_date.isoformat()
    default_config["end_date"] = end_date.isoformat()
    default_config["initial_capital"] = initial_capital
    default_config["transaction_cost_bps"] = (
        transaction_cost_bps_edit if transaction_cost_bps_edit is not None else 5
    )
    default_config["allocation"] = {
        "entry_mode": "percent_of_equity",
        "entry_value": allocation_value,
        "max_position_pct": (
            max_position_pct_edit if max_position_pct_edit is not None else 1.0
        ),
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

    return default_config


def _build_update_flow_default_config(
    *,
    base_config: dict[str, Any],
    tradable_symbol: str,
    benchmark_symbol: str,
    start_date,
    end_date,
    initial_capital: float,
    allocation_value: float,
    entry_rule: dict | None,
    exit_rule: dict | None,
    explicit_date_edits: dict[str, str],
) -> dict[str, Any]:
    default_config = dict(base_config)

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

    return default_config


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
    entry_rule = None
    exit_rule = None

    rsi_buy = _extract_rsi_rule(prompt, direction="below")
    rsi_sell = _extract_rsi_rule(prompt, direction="above")
    rsi_entry_threshold_edit = _extract_rsi_entry_threshold_edit(prompt)
    rsi_exit_threshold_edit = _extract_rsi_exit_threshold_edit(prompt)
    rsi_entry_lookback_edit = _extract_rsi_entry_lookback_edit(prompt)
    rsi_exit_lookback_edit = _extract_rsi_exit_lookback_edit(prompt)
    has_partial_rsi_edit = any(
        value is not None
        for value in (
            rsi_entry_threshold_edit,
            rsi_exit_threshold_edit,
            rsi_entry_lookback_edit,
            rsi_exit_lookback_edit,
        )
    )
    sma_pair = _extract_sma_crossover_pair(prompt)
    sma_above_pair = _extract_sma_above_pair(prompt)

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
        selected_pair = sma_above_pair if sma_above_pair is not None else sma_pair
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
        current_tradable_symbol = default_config.get("tradable_symbol", tradable_symbol)
        current_benchmark_symbol = default_config.get("benchmark_symbol", benchmark_symbol)

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
        current_tradable_symbol = default_config.get("tradable_symbol", tradable_symbol)
        current_benchmark_symbol = default_config.get("benchmark_symbol", benchmark_symbol)

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
        current_tradable_symbol = default_config.get("tradable_symbol", tradable_symbol)
        current_benchmark_symbol = default_config.get("benchmark_symbol", benchmark_symbol)

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
        or re.search(r"%\s+of\s+equity|allocation|allocate|max\s+position", prompt_lower)
    ):
        allocation = dict(default_config.get("allocation", {}))
        allocation["entry_mode"] = "percent_of_equity"
        if allocation_edit_value is not None or re.search(r"%\s+of\s+equity|allocation|allocate", prompt_lower):
            allocation["entry_value"] = (
                allocation_edit_value if allocation_edit_value is not None else allocation_value
            )
        allocation.setdefault("max_position_pct", 1.0)
        if max_position_pct_edit is not None:
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