from __future__ import annotations

from typing import Any


IDENTITY_CHANGE_MESSAGE = (
    "Changing the tradable symbol creates a different strategy. "
    "Start a new strategy from Home instead."
)

IDENTITY_NAME_CHANGE_MESSAGE = (
    "Strategy name is managed by the saved strategy. "
    "Use the change note to describe version changes."
)


def _normalized_symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().upper()
    return cleaned or None


def get_tradable_symbol(config: dict[str, Any]) -> str | None:
    return _normalized_symbol(config.get("tradable_symbol")) or _normalized_symbol(config.get("symbol"))


def _collect_rule_symbols(rule: Any) -> list[str]:
    symbols: list[str] = []
    if not isinstance(rule, dict):
        return symbols

    symbol = _normalized_symbol(rule.get("symbol"))
    if symbol is not None:
        symbols.append(symbol)

    for key in ("rule",):
        symbols.extend(_collect_rule_symbols(rule.get(key)))

    for key in ("rules", "steps"):
        children = rule.get(key)
        if isinstance(children, list):
            for child in children:
                symbols.extend(_collect_rule_symbols(child))

    return symbols


def validate_strategy_version_identity(
    *,
    current_config: dict[str, Any],
    new_config: dict[str, Any],
) -> None:
    current_symbol = get_tradable_symbol(current_config)
    new_symbol = get_tradable_symbol(new_config)

    if current_symbol is None or new_symbol is None:
        return

    if new_symbol != current_symbol:
        raise ValueError(IDENTITY_CHANGE_MESSAGE)

    top_level_symbol = _normalized_symbol(new_config.get("symbol"))
    if top_level_symbol is not None and top_level_symbol != current_symbol:
        raise ValueError(IDENTITY_CHANGE_MESSAGE)

    rule_symbols = [
        *_collect_rule_symbols(new_config.get("entry_rule")),
        *_collect_rule_symbols(new_config.get("exit_rule")),
    ]
    if any(symbol != current_symbol for symbol in rule_symbols):
        raise ValueError(IDENTITY_CHANGE_MESSAGE)


def normalize_strategy_version_identity_fields(
    *,
    strategy_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(config)
    normalized["name"] = strategy_name
    return normalized
