from __future__ import annotations

from typing import Any

from market_simulator.services.strategy_builder_parsers import (
    _build_position_management,
)
from market_simulator.services.strategy_builder_summary import (
    _build_strategy_name,
)

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
    overlay_allocation_pct: float | None,
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
    exit_behavior_edit: str | None,
    profit_reduce_threshold_edit: float | None,
    max_scale_in_steps_edit: int | None,
    min_bars_between_scale_ins_edit: int | None,
    remove_max_scale_in_steps: bool,
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
        "entry_value": (
            overlay_allocation_pct
            if overlay_allocation_pct is not None
            else allocation_value
        ),
        "max_position_pct": (
            max_position_pct_edit
            if max_position_pct_edit is not None
            else overlay_allocation_pct
            if overlay_allocation_pct is not None
            else 1.0
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
            exit_behavior=exit_behavior_edit,
            profit_reduce_threshold=profit_reduce_threshold_edit,
            max_scale_in_steps=max_scale_in_steps_edit,
            min_bars_between_scale_ins=min_bars_between_scale_ins_edit,
            remove_max_scale_in_steps=remove_max_scale_in_steps,
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


__all__ = [
    "_merge_dict",
    "_build_create_flow_default_config",
    "_build_update_flow_default_config",
]
