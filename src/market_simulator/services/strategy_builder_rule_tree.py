from __future__ import annotations

from typing import Any

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


def _has_rsi_rule(rule: Any, *, rule_type: str) -> bool:
    if not isinstance(rule, dict):
        return False

    kind = rule.get("kind")

    if kind == "atomic":
        return rule.get("type") == rule_type

    if kind == "not":
        return _has_rsi_rule(rule.get("rule"), rule_type=rule_type)

    if kind == "group":
        return any(_has_rsi_rule(child_rule, rule_type=rule_type) for child_rule in rule.get("rules", []))

    if kind == "window":
        return _has_rsi_rule(rule.get("rule"), rule_type=rule_type)

    if kind == "sequence":
        return any(_has_rsi_rule(step, rule_type=rule_type) for step in rule.get("steps", []))

    return False


def _update_rsi_rules(
    rule: Any,
    *,
    rule_type: str,
    threshold_edit: float | None,
    lookback_edit: int | None,
) -> Any:
    if not isinstance(rule, dict):
        return rule

    kind = rule.get("kind")
    updated_rule = dict(rule)

    if kind == "atomic":
        if updated_rule.get("type") == rule_type:
            if threshold_edit is not None:
                updated_rule["threshold"] = threshold_edit
            if lookback_edit is not None:
                updated_rule["lookback"] = lookback_edit
        return updated_rule

    if kind == "not":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_rsi_rules(
                nested_rule,
                rule_type=rule_type,
                threshold_edit=threshold_edit,
                lookback_edit=lookback_edit,
            )
        return updated_rule

    if kind == "group":
        updated_rule["rules"] = [
            _update_rsi_rules(
                child_rule,
                rule_type=rule_type,
                threshold_edit=threshold_edit,
                lookback_edit=lookback_edit,
            )
            if isinstance(child_rule, dict)
            else child_rule
            for child_rule in updated_rule.get("rules", [])
        ]
        return updated_rule

    if kind == "window":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_rsi_rules(
                nested_rule,
                rule_type=rule_type,
                threshold_edit=threshold_edit,
                lookback_edit=lookback_edit,
            )
        return updated_rule

    if kind == "sequence":
        updated_rule["steps"] = [
            _update_rsi_rules(
                step,
                rule_type=rule_type,
                threshold_edit=threshold_edit,
                lookback_edit=lookback_edit,
            )
            if isinstance(step, dict)
            else step
            for step in updated_rule.get("steps", [])
        ]
        return updated_rule

    return updated_rule


def _has_moving_average_rule(rule: Any) -> bool:
    if not isinstance(rule, dict):
        return False

    kind = rule.get("kind")

    if kind == "atomic":
        return rule.get("type") in {"sma_cross_above", "sma_cross_below", "sma_above"}

    if kind == "not":
        return _has_moving_average_rule(rule.get("rule"))

    if kind == "group":
        return any(_has_moving_average_rule(child_rule) for child_rule in rule.get("rules", []))

    if kind == "window":
        return _has_moving_average_rule(rule.get("rule"))

    if kind == "sequence":
        return any(_has_moving_average_rule(step) for step in rule.get("steps", []))

    return False


def _update_moving_average_rules(
    rule: Any,
    *,
    fast_window_edit: int | None,
    slow_window_edit: int | None,
) -> Any:
    if not isinstance(rule, dict):
        return rule

    kind = rule.get("kind")
    updated_rule = dict(rule)

    if kind == "atomic":
        if updated_rule.get("type") in {"sma_cross_above", "sma_cross_below", "sma_above"}:
            if fast_window_edit is not None:
                updated_rule["fast_window"] = fast_window_edit
            if slow_window_edit is not None:
                updated_rule["slow_window"] = slow_window_edit
        return updated_rule

    if kind == "not":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_moving_average_rules(
                nested_rule,
                fast_window_edit=fast_window_edit,
                slow_window_edit=slow_window_edit,
            )
        return updated_rule

    if kind == "group":
        updated_rule["rules"] = [
            _update_moving_average_rules(
                child_rule,
                fast_window_edit=fast_window_edit,
                slow_window_edit=slow_window_edit,
            )
            if isinstance(child_rule, dict)
            else child_rule
            for child_rule in updated_rule.get("rules", [])
        ]
        return updated_rule

    if kind == "window":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_moving_average_rules(
                nested_rule,
                fast_window_edit=fast_window_edit,
                slow_window_edit=slow_window_edit,
            )
        return updated_rule

    if kind == "sequence":
        updated_rule["steps"] = [
            _update_moving_average_rules(
                step,
                fast_window_edit=fast_window_edit,
                slow_window_edit=slow_window_edit,
            )
            if isinstance(step, dict)
            else step
            for step in updated_rule.get("steps", [])
        ]
        return updated_rule

    return updated_rule


def _has_month_in_rule(rule: Any) -> bool:
    if not isinstance(rule, dict):
        return False

    kind = rule.get("kind")

    if kind == "atomic":
        return rule.get("type") == "month_in"

    if kind == "not":
        return _has_month_in_rule(rule.get("rule"))

    if kind == "group":
        return any(_has_month_in_rule(child_rule) for child_rule in rule.get("rules", []))

    if kind == "window":
        return _has_month_in_rule(rule.get("rule"))

    if kind == "sequence":
        return any(_has_month_in_rule(step) for step in rule.get("steps", []))

    return False


def _update_month_in_rules(
    rule: Any,
    *,
    action: str,
    month_values: list[int],
) -> Any:
    if not isinstance(rule, dict):
        return rule

    kind = rule.get("kind")
    updated_rule = dict(rule)

    if kind == "atomic":
        if updated_rule.get("type") == "month_in":
            existing = list(updated_rule.get("month_values", []) or [])

            if action == "set":
                new_month_values = sorted(dict.fromkeys(month_values))
            elif action == "add":
                new_month_values = sorted(dict.fromkeys([*existing, *month_values]))
            elif action == "remove":
                new_month_values = [month for month in existing if month not in set(month_values)]
            else:
                new_month_values = existing

            if not new_month_values:
                raise ValueError("Seasonality rules must keep at least one month.")

            updated_rule["month_values"] = new_month_values

        return updated_rule

    if kind == "not":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_month_in_rules(
                nested_rule,
                action=action,
                month_values=month_values,
            )
        return updated_rule

    if kind == "group":
        updated_rule["rules"] = [
            _update_month_in_rules(
                child_rule,
                action=action,
                month_values=month_values,
            )
            if isinstance(child_rule, dict)
            else child_rule
            for child_rule in updated_rule.get("rules", [])
        ]
        return updated_rule

    if kind == "window":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_month_in_rules(
                nested_rule,
                action=action,
                month_values=month_values,
            )
        return updated_rule

    if kind == "sequence":
        updated_rule["steps"] = [
            _update_month_in_rules(
                step,
                action=action,
                month_values=month_values,
            )
            if isinstance(step, dict)
            else step
            for step in updated_rule.get("steps", [])
        ]
        return updated_rule

    return updated_rule


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


def _has_confirmation_rule(
    rule: dict,
    *,
    family: str,
    side: str,
) -> bool:
    kind = rule.get("kind")

    if kind == "atomic":
        return _matches_confirmation_rule(rule, family=family, side=side)

    if kind == "group":
        return any(
            _has_confirmation_rule(child_rule, family=family, side=side)
            for child_rule in rule.get("rules", [])
            if isinstance(child_rule, dict)
        )

    if kind == "not":
        nested_rule = rule.get("rule")
        return isinstance(nested_rule, dict) and _has_confirmation_rule(
            nested_rule,
            family=family,
            side=side,
        )

    if kind == "window":
        nested_rule = rule.get("rule")
        return isinstance(nested_rule, dict) and _has_confirmation_rule(
            nested_rule,
            family=family,
            side=side,
        )

    if kind == "sequence":
        return any(
            _has_confirmation_rule(step, family=family, side=side)
            for step in rule.get("steps", [])
            if isinstance(step, dict)
        )

    return False


def _remove_confirmation_rule(
    base_rule: dict,
    *,
    family: str,
    side: str,
) -> dict:
    def _remove_recursive(rule: dict) -> dict:
        kind = rule.get("kind")

        if kind == "group":
            original_rules = list(rule.get("rules", []))
            updated_children: list[dict] = []

            for child_rule in original_rules:
                if _matches_confirmation_rule(child_rule, family=family, side=side):
                    continue
                if isinstance(child_rule, dict):
                    updated_children.append(_remove_recursive(child_rule))
                else:
                    updated_children.append(child_rule)

            if len(updated_children) == len(original_rules):
                return rule

            if not updated_children:
                return rule

            if len(updated_children) == 1:
                return updated_children[0]

            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule

        if kind == "not":
            nested_rule = rule.get("rule")
            if isinstance(nested_rule, dict):
                updated_rule = dict(rule)
                updated_rule["rule"] = _remove_recursive(nested_rule)
                return updated_rule
            return rule

        if kind == "window":
            nested_rule = rule.get("rule")
            if isinstance(nested_rule, dict):
                updated_rule = dict(rule)
                updated_rule["rule"] = _remove_recursive(nested_rule)
                return updated_rule
            return rule

        if kind == "sequence":
            original_steps = list(rule.get("steps", []))
            updated_steps = [
                _remove_recursive(step) if isinstance(step, dict) else step
                for step in original_steps
            ]
            if updated_steps == original_steps:
                return rule
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule

        return rule

    return _remove_recursive(base_rule)


def _try_add_confirmation_rule_recursively(
    base_rule: dict,
    *,
    confirmation_rule: dict,
    family: str,
    side: str,
) -> tuple[dict, bool]:
    if _has_confirmation_rule(base_rule, family=family, side=side):
        return base_rule, False

    kind = base_rule.get("kind")

    if kind == "group" and base_rule.get("operator") == "AND":
        return _add_confirmation_rule(base_rule, confirmation_rule), True

    if kind == "window":
        nested_rule = base_rule.get("rule")
        if isinstance(nested_rule, dict) and nested_rule.get("kind") != "not":
            if nested_rule.get("kind") == "group" and nested_rule.get("operator") == "AND":
                updated_nested_rule = _add_confirmation_rule(nested_rule, confirmation_rule)
                updated_rule = dict(base_rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True

            if nested_rule.get("kind") == "atomic":
                updated_rule = dict(base_rule)
                updated_rule["rule"] = _add_confirmation_rule(nested_rule, confirmation_rule)
                return updated_rule, True

            updated_nested_rule, changed = _try_add_confirmation_rule_recursively(
                nested_rule,
                confirmation_rule=confirmation_rule,
                family=family,
                side=side,
            )
            if changed:
                updated_rule = dict(base_rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True

    return base_rule, False


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


def _remove_not_wrapper(rule: dict) -> dict:
    if rule.get("kind") != "not":
        return rule
    inner_rule = rule.get("rule")
    if isinstance(inner_rule, dict) and inner_rule:
        return inner_rule
    return rule


def _has_not_rule_anywhere(rule: Any) -> bool:
    if not isinstance(rule, dict):
        return False

    kind = rule.get("kind")

    if kind == "not":
        return True

    if kind == "group":
        return any(_has_not_rule_anywhere(child_rule) for child_rule in rule.get("rules", []))

    if kind == "window":
        return _has_not_rule_anywhere(rule.get("rule"))

    if kind == "sequence":
        return any(_has_not_rule_anywhere(step) for step in rule.get("steps", []))

    return False


def _update_first_not_inner_rule(
    rule: Any,
    *,
    new_inner_rule: dict,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "not":
        updated_rule = dict(rule)
        updated_rule["rule"] = new_inner_rule
        return updated_rule, True

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _update_first_not_inner_rule(
                    child_rule,
                    new_inner_rule=new_inner_rule,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_not_inner_rule(
                nested_rule,
                new_inner_rule=new_inner_rule,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True

        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _update_first_not_inner_rule(
                    step,
                    new_inner_rule=new_inner_rule,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _remove_first_not_wrapper(rule: Any) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "not":
        inner_rule = rule.get("rule")
        if isinstance(inner_rule, dict) and inner_rule:
            return inner_rule, True
        return rule, False

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _remove_first_not_wrapper(child_rule)
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _remove_first_not_wrapper(nested_rule)
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True

        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _remove_first_not_wrapper(step)
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


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


def _update_first_group_operator(
    rule: Any,
    *,
    operator: str,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "group":
        updated_rule = dict(rule)
        updated_rule["operator"] = operator
        return updated_rule, True

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_group_operator(
                nested_rule,
                operator=operator,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_group_operator(
                nested_rule,
                operator=operator,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _update_first_group_operator(
                    step,
                    operator=operator,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _update_first_group_condition(
    rule: Any,
    *,
    index: int,
    new_rule: dict,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "group":
        rules = list(rule.get("rules", []))
        if 0 <= index < len(rules):
            rules[index] = new_rule
            updated_rule = dict(rule)
            updated_rule["rules"] = rules
            return updated_rule, True

        updated_children = []
        changed = False
        for child_rule in rules:
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _update_first_group_condition(
                    child_rule,
                    index=index,
                    new_rule=new_rule,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_group_condition(
                nested_rule,
                index=index,
                new_rule=new_rule,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_group_condition(
                nested_rule,
                index=index,
                new_rule=new_rule,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _update_first_group_condition(
                    step,
                    index=index,
                    new_rule=new_rule,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _remove_first_group_condition(
    rule: Any,
    *,
    index: int,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "group":
        rules = list(rule.get("rules", []))
        if 0 <= index < len(rules):
            return _remove_group_condition(rule, index=index), True

        updated_children = []
        changed = False
        for child_rule in rules:
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _remove_first_group_condition(
                    child_rule,
                    index=index,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _remove_first_group_condition(
                nested_rule,
                index=index,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _remove_first_group_condition(
                nested_rule,
                index=index,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _remove_first_group_condition(
                    step,
                    index=index,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _update_first_window_bars(
    rule: Any,
    *,
    window_bars: int,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "window":
        updated_rule = dict(rule)
        updated_rule["window_bars"] = window_bars
        return updated_rule, True

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _update_first_window_bars(
                    child_rule,
                    window_bars=window_bars,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_window_bars(
                nested_rule,
                window_bars=window_bars,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _update_first_window_bars(
                    step,
                    window_bars=window_bars,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _update_first_window_mode(
    rule: Any,
    *,
    mode: str,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "window":
        updated_rule = dict(rule)
        updated_rule["mode"] = mode
        return updated_rule, True

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _update_first_window_mode(
                    child_rule,
                    mode=mode,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_window_mode(
                nested_rule,
                mode=mode,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _update_first_window_mode(
                    step,
                    mode=mode,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _update_first_window_inner_rule(
    rule: Any,
    *,
    new_inner_rule: dict,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "window":
        updated_rule = dict(rule)
        updated_rule["rule"] = new_inner_rule
        return updated_rule, True

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _update_first_window_inner_rule(
                    child_rule,
                    new_inner_rule=new_inner_rule,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_window_inner_rule(
                nested_rule,
                new_inner_rule=new_inner_rule,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _update_first_window_inner_rule(
                    step,
                    new_inner_rule=new_inner_rule,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _remove_first_window_wrapper(rule: Any) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "window":
        return _remove_window_wrapper(rule), True

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _remove_first_window_wrapper(child_rule)
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _remove_first_window_wrapper(nested_rule)
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "sequence":
        updated_steps = []
        changed = False
        for step in rule.get("steps", []):
            if not changed and isinstance(step, dict):
                updated_step, changed = _remove_first_window_wrapper(step)
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    return rule, False


def _update_first_sequence_bars(
    rule: Any,
    *,
    window_bars: int,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "sequence":
        updated_rule = dict(rule)
        updated_rule["window_bars"] = window_bars
        return updated_rule, True

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _update_first_sequence_bars(
                    child_rule,
                    window_bars=window_bars,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_sequence_bars(
                nested_rule,
                window_bars=window_bars,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_sequence_bars(
                nested_rule,
                window_bars=window_bars,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    return rule, False


def _update_first_sequence_step(
    rule: Any,
    *,
    index: int,
    new_step: dict,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "sequence":
        steps = list(rule.get("steps", []))
        if 0 <= index < len(steps):
            steps[index] = new_step
            updated_rule = dict(rule)
            updated_rule["steps"] = steps
            return updated_rule, True

        updated_steps = []
        changed = False
        for step in steps:
            if not changed and isinstance(step, dict):
                updated_step, changed = _update_first_sequence_step(
                    step,
                    index=index,
                    new_step=new_step,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _update_first_sequence_step(
                    child_rule,
                    index=index,
                    new_step=new_step,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_sequence_step(
                nested_rule,
                index=index,
                new_step=new_step,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _update_first_sequence_step(
                nested_rule,
                index=index,
                new_step=new_step,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    return rule, False


def _remove_first_sequence_step(
    rule: Any,
    *,
    index: int,
) -> tuple[Any, bool]:
    if not isinstance(rule, dict):
        return rule, False

    kind = rule.get("kind")

    if kind == "sequence":
        steps = list(rule.get("steps", []))
        if 0 <= index < len(steps):
            return _remove_sequence_step(rule, index=index), True

        updated_steps = []
        changed = False
        for step in steps:
            if not changed and isinstance(step, dict):
                updated_step, changed = _remove_first_sequence_step(
                    step,
                    index=index,
                )
                updated_steps.append(updated_step)
            else:
                updated_steps.append(step)

        if changed:
            updated_rule = dict(rule)
            updated_rule["steps"] = updated_steps
            return updated_rule, True

        return rule, False

    if kind == "group":
        updated_children = []
        changed = False
        for child_rule in rule.get("rules", []):
            if not changed and isinstance(child_rule, dict):
                updated_child, changed = _remove_first_sequence_step(
                    child_rule,
                    index=index,
                )
                updated_children.append(updated_child)
            else:
                updated_children.append(child_rule)

        if changed:
            updated_rule = dict(rule)
            updated_rule["rules"] = updated_children
            return updated_rule, True

        return rule, False

    if kind == "not":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _remove_first_sequence_step(
                nested_rule,
                index=index,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    if kind == "window":
        nested_rule = rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_nested_rule, changed = _remove_first_sequence_step(
                nested_rule,
                index=index,
            )
            if changed:
                updated_rule = dict(rule)
                updated_rule["rule"] = updated_nested_rule
                return updated_rule, True
        return rule, False

    return rule, False


def _has_relative_strength_rule(rule: Any) -> bool:
    if not isinstance(rule, dict):
        return False

    kind = rule.get("kind")
    if kind == "atomic":
        return rule.get("type") == "relative_return_above"

    if kind == "not":
        return _has_relative_strength_rule(rule.get("rule"))

    if kind == "group":
        return any(_has_relative_strength_rule(child_rule) for child_rule in rule.get("rules", []))

    if kind == "window":
        return _has_relative_strength_rule(rule.get("rule"))

    if kind == "sequence":
        return any(_has_relative_strength_rule(step) for step in rule.get("steps", []))

    return False


def _update_relative_strength_rules(
    rule: Any,
    *,
    reference_symbol_edit: str | None,
    lookback_edit: int | None,
    threshold_edit: float | None,
) -> Any:
    if not isinstance(rule, dict):
        return rule

    kind = rule.get("kind")
    updated_rule = dict(rule)

    if kind == "atomic":
        if updated_rule.get("type") == "relative_return_above":
            if reference_symbol_edit is not None:
                updated_rule["reference_symbol"] = reference_symbol_edit
            if lookback_edit is not None:
                updated_rule["lookback"] = lookback_edit
            if threshold_edit is not None:
                updated_rule["threshold"] = threshold_edit
        return updated_rule

    if kind == "not":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_relative_strength_rules(
                nested_rule,
                reference_symbol_edit=reference_symbol_edit,
                lookback_edit=lookback_edit,
                threshold_edit=threshold_edit,
            )
        return updated_rule

    if kind == "group":
        updated_rule["rules"] = [
            _update_relative_strength_rules(
                child_rule,
                reference_symbol_edit=reference_symbol_edit,
                lookback_edit=lookback_edit,
                threshold_edit=threshold_edit,
            )
            if isinstance(child_rule, dict)
            else child_rule
            for child_rule in updated_rule.get("rules", [])
        ]
        return updated_rule

    if kind == "window":
        nested_rule = updated_rule.get("rule")
        if isinstance(nested_rule, dict):
            updated_rule["rule"] = _update_relative_strength_rules(
                nested_rule,
                reference_symbol_edit=reference_symbol_edit,
                lookback_edit=lookback_edit,
                threshold_edit=threshold_edit,
            )
        return updated_rule

    if kind == "sequence":
        updated_rule["steps"] = [
            _update_relative_strength_rules(
                step,
                reference_symbol_edit=reference_symbol_edit,
                lookback_edit=lookback_edit,
                threshold_edit=threshold_edit,
            )
            if isinstance(step, dict)
            else step
            for step in updated_rule.get("steps", [])
        ]
        return updated_rule

    return updated_rule


def _collect_reference_symbols_from_rule(rule: Any) -> list[str]:
    symbols: list[str] = []

    if not isinstance(rule, dict):
        return symbols

    kind = rule.get("kind")

    if kind == "atomic":
        reference_symbol = rule.get("reference_symbol")
        if isinstance(reference_symbol, str):
            symbols.append(reference_symbol.upper())
        return symbols

    if kind == "not":
        return _collect_reference_symbols_from_rule(rule.get("rule"))

    if kind == "group":
        for child_rule in rule.get("rules", []):
            symbols.extend(_collect_reference_symbols_from_rule(child_rule))
        return symbols

    if kind == "window":
        return _collect_reference_symbols_from_rule(rule.get("rule"))

    if kind == "sequence":
        for step in rule.get("steps", []):
            symbols.extend(_collect_reference_symbols_from_rule(step))
        return symbols

    return symbols


def _sync_reference_symbols(config: dict[str, Any]) -> dict[str, Any]:
    synced_config = dict(config)

    tradable_symbol = synced_config.get("tradable_symbol")
    benchmark_symbol = synced_config.get("benchmark_symbol")

    collected: list[str] = []
    for key in ("entry_rule", "exit_rule"):
        collected.extend(_collect_reference_symbols_from_rule(synced_config.get(key)))

    deduped: list[str] = []
    for symbol in collected:
        if symbol not in deduped and symbol not in {tradable_symbol, benchmark_symbol}:
            deduped.append(symbol)

    synced_config["reference_symbols"] = deduped
    return synced_config


__all__ = [
    "_add_confirmation_rule",
    "_collect_reference_symbols_from_rule",
    "_has_confirmation_rule",
    "_has_month_in_rule",
    "_has_moving_average_rule",
    "_has_not_rule_anywhere",
    "_has_relative_strength_rule",
    "_has_rsi_rule",
    "_matches_confirmation_rule",
    "_remove_confirmation_rule",
    "_remove_first_group_condition",
    "_remove_first_not_wrapper",
    "_remove_first_sequence_step",
    "_remove_first_window_wrapper",
    "_remove_group_condition",
    "_remove_not_wrapper",
    "_remove_sequence_step",
    "_remove_window_wrapper",
    "_rewrite_rule_tradable_symbol",
    "_sync_reference_symbols",
    "_try_add_confirmation_rule_recursively",
    "_update_first_group_condition",
    "_update_first_group_operator",
    "_update_first_not_inner_rule",
    "_update_first_sequence_bars",
    "_update_first_sequence_step",
    "_update_first_window_bars",
    "_update_first_window_inner_rule",
    "_update_first_window_mode",
    "_update_month_in_rules",
    "_update_moving_average_rules",
    "_update_relative_strength_rules",
    "_update_rsi_rules",
]