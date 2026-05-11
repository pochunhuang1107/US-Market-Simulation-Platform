from __future__ import annotations

import copy
from datetime import date

import pandas as pd
import pytest
import market_simulator.services.strategy_builder_service as builder_service
import market_simulator.services.strategy_builder_parsers as builder_parsers
import market_simulator.services.strategy_builder_response as builder_response
from market_simulator import settings as settings_module
from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine import runner
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.parameter_sweep import (
    build_sweep_request,
    generate_variant_configs,
    get_nested,
)
from market_simulator.strategy.enricher import enrich_market_data
from market_simulator.strategy.evaluator import evaluate_rule
from market_simulator.settings import Settings, get_settings
from market_simulator.db.models import Plan


@pytest.fixture(autouse=True)
def default_builder_test_user(create_user, current_user_ctx):
    create_user(
        user_id=current_user_ctx["id"],
        email="builder-test@example.com",
    )


@pytest.fixture(autouse=True)
def default_builder_metadata_lookup(monkeypatch):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)


WORKSPACE_SAMPLE_PROMPTS = [
    pytest.param(
        "Create an XLE RSI pullback strategy with RSI below 45, exit above 60, 12% stop loss, 5-bar cooldown, and max position 75%.",
        id="xle-rsi-pullback",
    ),
    pytest.param(
        "Create an IWM RSI strategy that enters below 45, exits above 70, uses an 8% stop loss, and waits 3 bars after exits.",
        id="iwm-rsi-risk-control",
    ),
    pytest.param(
        "Create a QQQ strategy with entry when VIX below 30 and RSI below 40, exit when VIX above 40 or RSI above 70.",
        id="qqq-vix-rsi-filter",
    ),
    pytest.param(
        "Create a SPY strategy with entry when VIX below 30 and SPY is above its 100-day SMA, exit when SPY crosses below its 100-day SMA.",
        id="spy-defensive-trend",
    ),
    pytest.param(
        "Create an XLV RSI risk-control strategy that enters below 35, exits above 70, and uses an 8% stop loss.",
        id="xlv-risk-control",
    ),
    pytest.param(
        "Create a SPY core-overlay strategy with an 80% core and RSI overlay.",
        id="spy-core-overlay",
    ),
]


def _collect_rule_symbols(rule: dict | None) -> set[str]:
    if not isinstance(rule, dict):
        return set()

    symbols: set[str] = set()
    for key in ("symbol", "reference_symbol"):
        symbol = rule.get(key)
        if isinstance(symbol, str):
            symbols.add(symbol.upper())

    child = rule.get("rule")
    if isinstance(child, dict):
        symbols.update(_collect_rule_symbols(child))

    children = rule.get("rules")
    if isinstance(children, list):
        for child_rule in children:
            symbols.update(_collect_rule_symbols(child_rule))

    return symbols


def _assert_strategy_config_uses_supported_symbols(config: dict) -> None:
    settings = get_settings()
    supported_symbols = set(settings.supported_etf_symbols)
    supported_references = set(settings.supported_reference_series_symbols)
    symbols = {
        config["tradable_symbol"],
        config["benchmark_symbol"],
        *config.get("reference_symbols", []),
        *_collect_rule_symbols(config.get("entry_rule")),
        *_collect_rule_symbols(config.get("exit_rule")),
    }

    assert sorted(
        symbol
        for symbol in symbols
        if symbol not in supported_symbols and symbol not in supported_references
    ) == []


def _qqq_rsi_core_overlay_current_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-rsi-core-overlay-test",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": [],
        "start_date": "2019-01-02",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 0.4,
            "max_position_pct": 0.4,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 30,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 70,
        },
        "risk": {
            "stop_loss_pct": 0.08,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": True,
            "core_allocation_pct": 0.6,
        },
        "position_management": {
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "profit_reduce_threshold": None,
        },
    }


def _qqq_sma_current_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-sma-test",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": [],
        "start_date": "2021-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "sma_cross_above",
            "symbol": "QQQ",
            "fast_window": 10,
            "slow_window": 30,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "sma_cross_below",
            "symbol": "QQQ",
            "fast_window": 10,
            "slow_window": 30,
        },
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
        "position_management": None,
    }


def _qqq_vix_add_reduce_current_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "QQQ VIX Add Reduce Strategy",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": ["VIX"],
        "start_date": "2021-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 0.4,
            "max_position_pct": 1.0,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "series_below",
            "symbol": "VIX",
            "threshold": 15,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "series_above",
            "symbol": "VIX",
            "threshold": 35,
        },
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": True,
            "core_allocation_pct": 0.6,
        },
        "position_management": {
            "scale_in_fraction": 0.25,
            "scale_out_fraction": 0.5,
            "profit_reduce_threshold": None,
        },
    }


def _qqq_vix_rsi_current_config() -> dict:
    config = _qqq_vix_add_reduce_current_config()
    config["name"] = "QQQ VIX + RSI Strategy"
    config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 35,
            },
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 25,
            },
        ],
    }
    config["exit_rule"] = {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70,
    }
    return config


def _rotation_current_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "Multi-Asset Top-1 63D Rotation",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": ["SPY", "TLT", "XLK"],
        "start_date": "2021-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
        "position_management": None,
        "rotation": {
            "enabled": True,
            "universe": ["QQQ", "SPY", "XLK", "TLT"],
            "ranking": {
                "type": "relative_return",
                "lookback": 63,
                "descending": True,
            },
            "rebalance": {
                "frequency": "monthly",
                "day": "first_trading_day",
            },
            "selection": {
                "top_n": 1,
            },
            "allocation": {
                "weighting": "equal_weight",
                "max_position_pct": 1.0,
            },
            "risk_filter": None,
            "fallback": {
                "type": "cash",
            },
        },
    }


def test_generate_strategy_builder_response_includes_translation_metadata(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a QQQ RSI strategy that enters below 30 and exits above 70."
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    assert body["config"]["tradable_symbol"] == "QQQ"
    assert body["translation_provider"] == "deterministic"
    assert body["translation_mode"] == "deterministic"
    assert body["translation_fallback_used"] is False
    assert body["deterministic_attempted"] is True
    assert body["openai_attempted"] is False
    assert body["llm_enabled"] is False


def test_generate_strategy_builder_rotation_prompt_uses_deterministic_provider(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a monthly rotation between QQQ, SPY, XLK, and TLT using 3-month momentum."
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    assert body["config"]["rotation"]["enabled"] is True
    assert body["translation_provider"] == "deterministic"
    assert body["llm_enabled"] is False


def test_generate_strategy_builder_current_config_follow_up_remains_deterministic(client):
    current_config = _qqq_rsi_core_overlay_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Change max position to 50%.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"
    assert body["config"]["allocation"]["max_position_pct"] == 0.5
    assert body["translation_provider"] == "deterministic"


def test_disabled_llm_provider_setting_falls_back_without_calling_llm(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            strategy_builder_provider="llm",
            strategy_builder_llm_enabled=False,
        ),
    )

    def fail_if_llm_translate_is_called(*args, **kwargs):
        raise AssertionError("disabled LLM provider should not be called")

    monkeypatch.setattr(
        "market_simulator.services.strategy_translation.LlmTranslationProvider.translate",
        fail_if_llm_translate_is_called,
    )

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a QQQ RSI strategy that enters below 30 and exits above 70.",
            "context": {"mode": "llm"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    assert body["translation_provider"] == "deterministic"
    assert body["llm_enabled"] is False


def test_rotation_prompt_warns_when_unsupported_symbols_are_omitted(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a monthly rotation across QQQ, SPY, TSLA, and XLK using 3-month momentum."
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    assert "TSLA" not in body["config"]["rotation"]["universe"]
    assert any("TSLA" in warning for warning in body["warnings"])


def _assert_strategy_v2_config_preserves(
    config: dict,
    original: dict,
    *,
    changed_top_level: set[str] | None = None,
    changed_nested: dict[str, set[str]] | None = None,
) -> None:
    changed_top_level = changed_top_level or set()
    changed_nested = changed_nested or {}
    raw_original = copy.deepcopy(original)
    original = StrategyV2.model_validate(original).model_dump(mode="json", exclude_none=True)
    raw_original_position_management = raw_original.get("position_management")
    original_position_management = original.get("position_management")
    if isinstance(raw_original_position_management, dict) and isinstance(
        original_position_management,
        dict,
    ):
        for default_key in (
            "scale_in_fraction",
            "exit_behavior",
            "min_bars_between_scale_ins",
            "scale_in_requires_persistent_signal",
            "scale_out_fraction",
            "profit_reduce_threshold",
        ):
            if default_key not in raw_original_position_management:
                original_position_management.pop(default_key, None)

    for key in (
        {
            "tradable_symbol",
            "benchmark_symbol",
            "reference_symbols",
            "start_date",
            "end_date",
            "allocation",
            "entry_rule",
            "exit_rule",
            "risk",
            "core_overlay",
            "position_management",
        }
        - changed_top_level
        - set(changed_nested)
    ):
        assert config[key] == original[key]

    for key, changed_fields in changed_nested.items():
        for field, original_value in original[key].items():
            if field not in changed_fields:
                assert config[key][field] == original_value

    StrategyV2.model_validate(config)


def _post_strategy_builder_prompt(
    client,
    prompt: str,
    *,
    current_config: dict | None = None,
) -> dict:
    payload: dict = {"prompt": prompt}
    if current_config is not None:
        payload["context"] = {
            "mode": "NEW_VERSION",
            "current_config": current_config,
        }

    response = client.post("/strategy-builder/generate", json=payload)

    assert response.status_code == 200
    body = response.json()
    if body.get("config") is not None:
        StrategyV2.model_validate(body["config"])
    return body


def _append_unique_changes(history: list[str], changes: list[str] | None) -> list[str]:
    if not changes:
        return history

    next_history = list(history)
    seen = set(next_history)
    for change in changes:
        if change in seen:
            continue
        seen.add(change)
        next_history.append(change)
    return next_history


def _assert_no_change_mentions(changes: list[str], *phrases: str) -> None:
    normalized_changes = [change.lower() for change in changes]
    for phrase in phrases:
        assert not any(phrase.lower() in change for change in normalized_changes)


def _assert_rsi_entry_threshold_30(config: dict) -> None:
    assert config["entry_rule"]["threshold"] == 30


def _assert_rsi_exit_rule_65(config: dict) -> None:
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 65.0,
    }


def _assert_benchmark_spy(config: dict) -> None:
    assert config["benchmark_symbol"] == "SPY"


def _assert_stop_loss_8_pct(config: dict) -> None:
    assert config["risk"]["stop_loss_pct"] == 0.08


def _assert_no_stop_loss(config: dict) -> None:
    assert "stop_loss_pct" not in config["risk"]


def _assert_cooldown_5(config: dict) -> None:
    assert config["risk"]["cooldown_bars"] == 5


def _assert_max_position_50_pct(config: dict) -> None:
    assert config["allocation"]["max_position_pct"] == 0.5


@pytest.mark.parametrize(
    ("prompt", "changed_top_level", "changed_nested", "assert_update"),
    [
        (
            "change RSI entry to 30",
            {"entry_rule"},
            {},
            _assert_rsi_entry_threshold_30,
        ),
        (
            "change exit to RSI above 65",
            {"exit_rule"},
            {},
            _assert_rsi_exit_rule_65,
        ),
        (
            "change benchmark to SPY",
            {"benchmark_symbol"},
            {},
            _assert_benchmark_spy,
        ),
        (
            "set stop loss to 8%",
            set(),
            {"risk": {"stop_loss_pct"}},
            _assert_stop_loss_8_pct,
        ),
        (
            "remove stop loss",
            set(),
            {"risk": {"stop_loss_pct"}},
            _assert_no_stop_loss,
        ),
        (
            "set cooldown to 5 bars",
            set(),
            {"risk": {"cooldown_bars"}},
            _assert_cooldown_5,
        ),
        (
            "set max position to 50%",
            set(),
            {"allocation": {"max_position_pct"}},
            _assert_max_position_50_pct,
        ),
    ],
)
def test_generate_strategy_builder_follow_up_common_edits_preserve_unrelated_config(
    client,
    prompt,
    changed_top_level,
    changed_nested,
    assert_update,
):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["benchmark_symbol"] = "DIA"
    current_config["reference_symbols"] = ["SPY"]
    current_config["risk"]["take_profit_pct"] = 0.20
    current_config["position_management"]["max_scale_in_steps"] = 4
    current_config["position_management"]["min_bars_between_scale_ins"] = 3
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert_update(config)
    _assert_strategy_v2_config_preserves(
        config,
        original,
        changed_top_level=changed_top_level,
        changed_nested=changed_nested,
    )


def test_generate_strategy_builder_follow_up_rsi_sweep_uses_current_config(client):
    current_config = _qqq_rsi_core_overlay_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70. Rank by Sharpe.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"] == current_config
    assert sweep["grid"] == {
        "entry_rule.threshold": [20, 25, 30],
        "exit_rule.threshold": [60, 65, 70],
    }
    assert sweep["ranking_metric"] == "sharpe_ratio"
    assert sweep["variant_count"] == 9


def test_generate_strategy_builder_follow_up_rsi_range_sweep_uses_current_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Sweep RSI buy threshold from 20 to 30 and sell threshold 60 to 70.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {
        "entry_rule.threshold": [20, 25, 30],
        "exit_rule.threshold": [60, 65, 70],
    }
    assert sweep["variant_count"] == 9


def test_generate_strategy_builder_follow_up_sma_sweep_uses_sma_paths(client):
    current_config = _qqq_sma_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry slow windows 10, 20 and exit slow windows 20, 30.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"] == current_config
    assert sweep["grid"] == {
        "entry_rule.slow_window": [10, 20],
        "exit_rule.slow_window": [20, 30],
    }
    assert "entry_rule.threshold" not in sweep["grid"]
    assert "exit_rule.threshold" not in sweep["grid"]
    assert sweep["variant_count"] == 4


def test_generate_strategy_builder_follow_up_risk_sweep_parses_percent_and_cooldown(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try stop loss 5%, 10% and take profit 10%, 15% and cooldown 0, 5 bars.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {
        "risk.stop_loss_pct": [0.05, 0.1],
        "risk.take_profit_pct": [0.1, 0.15],
        "risk.cooldown_bars": [0, 5],
    }
    assert sweep["variant_count"] == 8


@pytest.mark.parametrize(
    "prompt",
    [
        "Try VIX add thresholds 10, 15, 20 and reduce thresholds 30, 35, 40.",
        "Sweep VIX below 10/15/20 and VIX above 30/35/40.",
        "Try add when VIX below 10, 15, 20 and reduce when VIX above 30, 35, 40.",
    ],
)
def test_generate_strategy_builder_follow_up_vix_add_reduce_threshold_sweep(
    client,
    prompt,
):
    current_config = _qqq_vix_add_reduce_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"] == current_config
    assert sweep["grid"] == {
        "entry_rule.threshold": [10, 15, 20],
        "exit_rule.threshold": [30, 35, 40],
    }
    assert sweep["variant_count"] == 9
    build_sweep_request(sweep)


@pytest.mark.parametrize(
    "prompt",
    [
        "Try scale-in 20%, 25%, 30% and scale-out 40%, 50%, 60%.",
        "Sweep overlay sizing with scale in 20/25/30 and scale out 40/50/60.",
    ],
)
def test_generate_strategy_builder_follow_up_scale_in_scale_out_sweep(client, prompt):
    current_config = _qqq_vix_add_reduce_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {
        "position_management.scale_in_fraction": [0.2, 0.25, 0.3],
        "position_management.scale_out_fraction": [0.4, 0.5, 0.6],
    }
    assert sweep["variant_count"] == 9
    build_sweep_request(sweep)


def test_generate_strategy_builder_follow_up_core_allocation_sweep(client):
    current_config = _qqq_vix_add_reduce_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try core allocations 40%, 50%, 60%, 70%.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {
        "core_overlay.core_allocation_pct": [0.4, 0.5, 0.6, 0.7],
    }
    assert sweep["variant_count"] == 4
    build_sweep_request(sweep)


def test_generate_strategy_builder_follow_up_vix_rsi_group_threshold_sweep(client):
    current_config = _qqq_vix_rsi_current_config()

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try VIX thresholds 20, 25, 30 and RSI thresholds 30, 35, 40.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    rsi_path = "entry_rule.rules[0].threshold"
    vix_path = "entry_rule.rules[1].threshold"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {
        vix_path: [20, 25, 30],
        rsi_path: [30, 35, 40],
    }
    assert get_nested(sweep["base_config"], vix_path) == 25
    assert get_nested(sweep["base_config"], rsi_path) == 35
    assert sweep["variant_count"] == 9
    build_sweep_request(sweep)


def test_generate_strategy_builder_follow_up_ambiguous_vix_threshold_sweep_returns_guidance(
    client,
):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try VIX thresholds 10, 15, 20.",
            "context": {"current_config": _qqq_vix_add_reduce_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert "multiple possible" in body["message"]


def test_generate_strategy_builder_follow_up_sweep_ranking_metric_total_return(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry thresholds 20, 25 and exit thresholds 60, 65. Rank by total return.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert body["sweep_draft"]["ranking_metric"] == "total_return_pct"


def test_generate_strategy_builder_follow_up_sweep_over_limit_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Try entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70 "
                "and stop loss 5%, 10%, 15%."
            ),
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == "This sweep would create 27 variants, but your plan allows up to 25."


def test_generate_strategy_builder_follow_up_mismatched_parameter_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try RSI thresholds 20, 30.",
            "context": {"current_config": _qqq_sma_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == (
        "This draft does not use RSI rules yet. You can create an RSI strategy first, "
        "or ask me to replace the entry/exit rules with RSI."
    )


def test_generate_strategy_builder_existing_sweep_allows_simple_grid_and_ranking_edits(client):
    current_sweep = {
        "title": "QQQ RSI Threshold Sweep",
        "base_config": _qqq_rsi_core_overlay_current_config(),
        "grid": {
            "entry_rule.threshold": [20, 25],
            "exit_rule.threshold": [60, 65],
        },
        "ranking_metric": "sharpe_ratio",
        "variant_count": 4,
        "max_variants": 25,
        "summary": "Existing sweep draft.",
    }

    add_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Add entry threshold 35.",
            "context": {"current_config": current_sweep},
        },
    )

    assert add_response.status_code == 200
    add_body = add_response.json()
    assert add_body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert add_body["sweep_draft"]["grid"]["entry_rule.threshold"] == [20, 25, 35]
    assert add_body["sweep_draft"]["variant_count"] == 6

    rank_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Rank by total return.",
            "context": {"current_config": add_body["sweep_draft"]},
        },
    )

    assert rank_response.status_code == 200
    rank_body = rank_response.json()
    assert rank_body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert rank_body["sweep_draft"]["ranking_metric"] == "total_return_pct"


def test_generate_strategy_builder_returns_rsi_parameter_sweep_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Test QQQ RSI entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70 "
                "from 2021-01-01 to 2024-12-31. Rank by Sharpe."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert body["config"] is None
    assert sweep["base_config"]["tradable_symbol"] == "QQQ"
    assert sweep["base_config"]["entry_rule"]["type"] == "rsi_below"
    assert sweep["base_config"]["exit_rule"]["type"] == "rsi_above"
    assert sweep["base_config"]["start_date"] == "2021-01-01"
    assert sweep["base_config"]["end_date"] == "2024-12-31"
    assert sweep["grid"] == {
        "entry_rule.threshold": [20, 25, 30],
        "exit_rule.threshold": [60, 65, 70],
    }
    assert sweep["ranking_metric"] == "sharpe_ratio"
    assert sweep["variant_count"] == 9
    assert sweep["max_variants"] == 25


def test_generate_strategy_builder_returns_sma_parameter_sweep_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try QQQ SMA fast windows 5, 10 and slow windows 20, 30",
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"]["entry_rule"]["type"] == "sma_cross_above"
    assert sweep["base_config"]["exit_rule"]["type"] == "sma_cross_below"
    assert sweep["grid"] == {
        "entry_rule.fast_window": [5, 10],
        "entry_rule.slow_window": [20, 30],
    }
    assert sweep["variant_count"] == 4


def test_generate_strategy_builder_parameter_sweep_ranking_metric_total_return(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Test QQQ RSI entry thresholds 20, 25 and exit thresholds 60, 65. "
                "Rank by total return."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert body["sweep_draft"]["ranking_metric"] == "total_return_pct"


def test_generate_strategy_builder_parameter_sweep_over_limit_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Test QQQ RSI entry thresholds 20, 25, 30 and exit thresholds 60, 65, 70 "
                "and stop loss 5%, 10%, 15%. Rank by Sharpe."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == "This sweep would create 27 variants, but your plan allows up to 25."


def test_generate_strategy_builder_normal_rsi_prompt_still_returns_strategy_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a simple RSI strategy for QQQ."},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "CREATE_DRAFT"
    assert body["sweep_draft"] is None
    assert body["config"]["entry_rule"]["type"] == "rsi_below"


def test_generate_strategy_builder_parses_bullish_candle_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes above its open."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "bullish_candle",
        "symbol": "QQQ",
    }
    assert "Enter when QQQ closes above its open." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_previous_low_exit_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes below yesterday's low."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "close_below_previous_low",
        "symbol": "QQQ",
    }
    assert "Exit when QQQ closes below the previous day's low." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_defaults_near_high_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes near the high of the day."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "close_near_high",
        "symbol": "QQQ",
        "threshold": 0.2,
    }
    assert "QQQ closes in the top 20% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_defaults_near_low_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes near the low of the day."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "close_near_low",
        "symbol": "QQQ",
        "threshold": 0.2,
    }
    assert "QQQ closes in the bottom 20% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_top_range_percentage_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes in the top 10% of the day's range."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "close_near_high",
        "symbol": "QQQ",
        "threshold": 0.1,
    }
    assert "QQQ closes in the top 10% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        not in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_bottom_range_percentage_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes in the bottom 15% of the day's range."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "close_near_low",
        "symbol": "QQQ",
        "threshold": 0.15,
    }
    assert "QQQ closes in the bottom 15% of the day's range" in body["summary"]
    assert (
        "Used top/bottom 20% of the daily range for near-high/near-low candle signals by default."
        not in body["assumptions"]
    )
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_within_candle_percentage_thresholds(client):
    top_response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when QQQ closes within the top 10% of the candle."},
    )
    bottom_response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when QQQ closes within the bottom 15% of the candle."},
    )

    assert top_response.status_code == 200
    assert bottom_response.status_code == 200
    top_config = top_response.json()["config"]
    bottom_config = bottom_response.json()["config"]

    assert top_config["entry_rule"]["type"] == "close_near_high"
    assert top_config["entry_rule"]["threshold"] == 0.1
    assert bottom_config["exit_rule"]["type"] == "close_near_low"
    assert bottom_config["exit_rule"]["threshold"] == 0.15
    StrategyV2.model_validate(top_config)
    StrategyV2.model_validate(bottom_config)


def test_generate_strategy_builder_parses_bullish_entry_and_previous_low_exit_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when QQQ closes above its open. "
                "Sell when QQQ closes below yesterday's low."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "bullish_candle"
    assert config["exit_rule"]["type"] == "close_below_previous_low"
    assert "Enter when QQQ closes above its open." in body["summary"]
    assert "Exit when QQQ closes below the previous day's low." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_adds_candle_rule_symbol_to_reference_symbols(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when SPY closes above its open."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "bullish_candle"
    assert config["entry_rule"]["symbol"] == "SPY"
    assert config["reference_symbols"] == ["SPY"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_composite_entry_and_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when RSI 14 is below 30 and QQQ is above its 200-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert config["entry_rule"]["rules"][1] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "QQQ",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert "Enter when QQQ RSI(14) is below 30 and QQQ price is above its 200-day SMA." in body["summary"]
    assert "Exit when QQQ RSI(14) is above 70." in body["summary"]


def test_generate_strategy_builder_composite_rsi_and_daily_candle_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when RSI is below 30 and QQQ closes near the high of the day. "
                "Sell when RSI is above 70 or QQQ closes below yesterday's low."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][0]["symbol"] == "QQQ"
    assert config["entry_rule"]["rules"][0]["threshold"] == 30.0
    assert config["entry_rule"]["rules"][1] == {
        "kind": "atomic",
        "type": "close_near_high",
        "symbol": "QQQ",
        "threshold": 0.2,
    }
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][0]["symbol"] == "QQQ"
    assert config["exit_rule"]["rules"][0]["threshold"] == 70.0
    assert config["exit_rule"]["rules"][1] == {
        "kind": "atomic",
        "type": "close_below_previous_low",
        "symbol": "QQQ",
    }
    assert "QQQ closes in the top 20% of the day's range" in body["summary"]
    assert "QQQ closes below the previous day's low" in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_simple_price_above_sma_prompt_uses_requested_window(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ is above its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "QQQ",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert "Enter when QQQ price is above its 200-day SMA." in body["summary"]
    assert "20-day SMA" not in body["summary"]
    assert "50-day SMA" not in body["summary"]


def test_generate_strategy_builder_follow_up_sma_sweep_targets_price_sma_window(client):
    draft_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ is above its 200-day SMA."
            ),
        },
    )
    assert draft_response.status_code == 200
    current_config = draft_response.json()["config"]

    sweep_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try SMA windows 100, 150, 200.",
            "context": {"current_config": current_config},
        },
    )

    assert sweep_response.status_code == 200
    body = sweep_response.json()
    sweep = body["sweep_draft"]
    path = "entry_rule.slow_window"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [100, 150, 200]}
    assert get_nested(sweep["base_config"], path) == 200

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [100, 150, 200]
    assert {variant["config"]["entry_rule"]["fast_window"] for variant in variants} == {1}


def test_generate_strategy_builder_composite_explicit_symbol_sma_crossover_preserves_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ 20-day SMA crosses above QQQ 50-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_cross_above",
        "symbol": "QQQ",
        "fast_window": 20,
        "slow_window": 50,
    }
    assert "Enter when QQQ 20-day SMA crosses above QQQ 50-day SMA." in body["summary"]
    assert "QQQ crosses above its 20-day SMA" not in body["summary"]
    assert "QQQ price is above its 20-day SMA" not in body["summary"]


def test_generate_strategy_builder_composite_explicit_sma_crossover_preserves_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when 20-day SMA crosses above 50-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 20
    assert config["entry_rule"]["slow_window"] == 50
    assert "Enter when QQQ 20-day SMA crosses above QQQ 50-day SMA." in body["summary"]


def test_generate_strategy_builder_composite_explicit_sma_cross_below_preserves_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Buy when QQQ 50-day SMA crosses below QQQ 200-day SMA. "
                "Sell when RSI 14 is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_cross_below",
        "symbol": "QQQ",
        "fast_window": 50,
        "slow_window": 200,
    }
    assert "Enter when QQQ 50-day SMA crosses below QQQ 200-day SMA." in body["summary"]


def test_generate_strategy_builder_composite_exit_or_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when RSI 14 is below 30. "
                "Sell QQQ when RSI 14 is above 70 or QQQ is below its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "QQQ",
            "fast_window": 1,
            "slow_window": 200,
        },
    }
    assert "Exit when QQQ RSI(14) is above 70 or QQQ price is no longer above its 200-day SMA." in body["summary"]


def test_generate_strategy_builder_simple_price_below_sma_exit_prompt_uses_requested_window(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2021-01-01 to 2024-12-31. "
                "Sell when QQQ falls below its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "QQQ",
            "fast_window": 1,
            "slow_window": 200,
        },
    }
    assert "Exit when QQQ price is no longer above its 200-day SMA." in body["summary"]
    assert "20-day SMA" not in body["summary"]
    assert "50-day SMA" not in body["summary"]


def test_generate_strategy_builder_composite_reference_symbol_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy. "
                "Buy when QQQ RSI is below 30 and SPY is above its 200 day SMA. "
                "Sell when QQQ RSI is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert "SPY" in config["reference_symbols"]
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["rules"][1]["symbol"] == "SPY"
    assert config["entry_rule"]["rules"][1]["type"] == "sma_above"


def test_generate_strategy_builder_reference_symbol_trend_filter_with_rsi(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy that buys when RSI is below 30 and "
                "SPY is above its 200-day SMA. Sell when RSI is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]
    entry_rules = config["entry_rule"]["rules"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["name"] == "qqq-rsi-with-spy-trend-filter"
    assert config["name"] != "qqq-and-to-rsi-above"
    assert config["tradable_symbol"] == "QQQ"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert entry_rules[0] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert entry_rules[1] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70.0,
    }
    assert "Enter when QQQ RSI(14) is below 30 and SPY price is above its 200-day SMA." in body["summary"]
    assert "Exit when QQQ RSI(14) is above 70." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_entry_only_reference_symbol_trend_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Trade QQQ only when SPY is above its 200-day SMA."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert config["exit_rule"] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 200,
        },
    }
    assert "Enter when SPY price is above its 200-day SMA." in body["summary"]
    assert "Exit when SPY price is no longer above its 200-day SMA." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_vix_entry_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Buy QQQ when VIX is below 25."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 25.0,
    }
    assert "VIX" in config["reference_symbols"]
    assert "Enter when VIX is below 25." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_names_pure_vix_entry_exit_strategy_readably(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Buy QQQ when VIX is below 15 and sell when VIX is above 35.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["name"] == "QQQ VIX Strategy"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 15.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "VIX",
        "threshold": 35.0,
    }
    assert "VIX" in config["reference_symbols"]
    StrategyV2.model_validate(config)


@pytest.mark.parametrize(
    "prompt",
    [
        "Buy and hold QQQ. Reduce when VIX is over 35. Add when VIX below 15.",
        "Buy and hold QQQ. Add when VIX is below 15. Reduce when VIX is above 35.",
        "Hold QQQ core. Add when VIX below 15 and reduce when VIX above 35.",
    ],
)
def test_generate_strategy_builder_parses_vix_add_reduce_core_overlay_prompt(
    client,
    prompt,
):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["name"] == "QQQ VIX Add Reduce Strategy"
    assert config["tradable_symbol"] == "QQQ"
    assert "VIX" in config["reference_symbols"]
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 15.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "VIX",
        "threshold": 35.0,
    }
    assert config["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.60,
    }
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["scale_out_fraction"] == 0.50
    assert config["position_management"].get("profit_reduce_threshold") is None
    assert config["allocation"]["max_position_pct"] == 1.0
    assert "Enter/add overlay when VIX is below 15." in body["summary"]
    assert "Reduce overlay when VIX is above 35." in body["summary"]
    assert any(
        assumption
        in {
            "Interpreted buy-and-hold language as a core QQQ sleeve.",
            "Interpreted core language as a core QQQ sleeve.",
        }
        for assumption in body["assumptions"]
    )
    assert "Used 60% core and 40% tactical overlay by default." in body["assumptions"]
    assert "Used 60.0% core allocation by default." not in body["assumptions"]
    assert (
        body["assumptions"].count("Used 60% core and 40% tactical overlay by default.")
        == 1
    )
    assert "Used 25% scale-in and 50% scale-out by default." in body["assumptions"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_vix_add_reduce_keeps_explicit_core_allocation_assumption(
    client,
):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy and hold QQQ with core allocation at 55%. "
                "Reduce when VIX is over 35. Add when VIX below 15."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.55,
    }
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 15.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "VIX",
        "threshold": 35.0,
    }
    assert "Used explicit 55% core allocation." in body["assumptions"]
    assert "Used 60% core and 40% tactical overlay by default." not in body["assumptions"]
    assert "Used 60.0% core allocation by default." not in body["assumptions"]
    assert "Used 25% scale-in and 50% scale-out by default." in body["assumptions"]
    StrategyV2.model_validate(config)


@pytest.mark.parametrize(
    "prompt",
    [
        "Buy and hold QQQ.",
        "Buy and hold QQQ. Add when VIX is calm and reduce when VIX is high.",
        "Reduce when VIX is over 35.",
        "Add when VIX below 15.",
        "Trim when VIX is over 35.",
        "Increase exposure when VIX below 15.",
        "Decrease exposure when VIX over 35.",
    ],
)
def test_generate_strategy_builder_rejects_unsupported_allocation_adjustment_phrases(
    client,
    prompt,
):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "explicit reference-series thresholds" in body["message"]


def test_generate_strategy_builder_parses_composite_rsi_and_vix_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Only trade QQQ when VIX is below 25 and RSI is below 35.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]
    entry_rules = config["entry_rule"]["rules"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["name"] == "QQQ VIX + RSI Strategy"
    assert config["name"] != "qqq-and-to-rsi-above"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert entry_rules[0] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 25.0,
    }
    assert entry_rules[1] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 35.0,
    }
    assert "VIX" in config["reference_symbols"]
    strategy = StrategyV2.model_validate(config)

    bundle = MarketDataBundle(
        tradable=pd.DataFrame(
            {
                "date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"]),
                "symbol": ["QQQ", "QQQ", "QQQ"],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.0, 101.0, 102.0],
                "volume": [1_000_000.0, 1_000_000.0, 1_000_000.0],
                "vwap": [100.0, 101.0, 102.0],
                "transactions": [10_000.0, 10_000.0, 10_000.0],
                "rsi_14": [30.0, 30.0, 30.0],
            }
        ),
        references={
            "VIX": pd.DataFrame(
                {
                    "date": pd.to_datetime(["2021-01-04", "2021-01-06"]),
                    "symbol": ["VIX", "VIX"],
                    "value": [30.0, 20.0],
                }
            )
        },
    )

    result = runner.run_simulation(bundle, strategy)

    assert [row["entry_signal"] for row in result.timeline] == [False, False, True]
    assert result.timeline[1]["action_taken"] == ""


@pytest.mark.parametrize(
    ("prompt", "expected_entry_rule", "expected_exit_rule"),
    [
        (
            "only trade QQQ when VIX is below 25 and RSI is below 35",
            {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "series_below",
                        "symbol": "VIX",
                        "threshold": 25.0,
                    },
                    {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 35.0,
                    },
                ],
            },
            None,
        ),
        (
            "exit when VIX is above 35",
            None,
            {
                "kind": "atomic",
                "type": "series_above",
                "symbol": "VIX",
                "threshold": 35.0,
            },
        ),
        (
            "buy QQQ when RSI below 35 and VIX below 20",
            {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 35.0,
                    },
                    {
                        "kind": "atomic",
                        "type": "series_below",
                        "symbol": "VIX",
                        "threshold": 20.0,
                    },
                ],
            },
            None,
        ),
    ],
)
def test_generate_strategy_builder_common_vix_reference_prompts_validate_cleanly(
    client,
    prompt,
    expected_entry_rule,
    expected_exit_rule,
):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["reference_symbols"] == ["VIX"]
    if expected_entry_rule is not None:
        assert config["entry_rule"] == expected_entry_rule
    if expected_exit_rule is not None:
        assert config["exit_rule"] == expected_exit_rule
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_vix_exit_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Sell when VIX is above 35."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "VIX",
        "threshold": 35.0,
    }
    assert "VIX" in config["reference_symbols"]
    assert "Exit when VIX is above 35." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_10y_yield_alias(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when the 10Y yield is below 4.5%."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "DGS10",
        "threshold": 4.5,
    }
    assert "DGS10" in config["reference_symbols"]
    assert "Enter when the 10-year Treasury yield is below 4.5%." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_inverted_yield_curve(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when the yield curve is inverted."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "T10Y2Y",
        "threshold": 0.0,
    }
    assert "T10Y2Y" in config["reference_symbols"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_parses_t10y2y_direct_above_filter(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when T10Y2Y is above 0."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "T10Y2Y",
        "threshold": 0.0,
    }
    assert "T10Y2Y" in config["reference_symbols"]
    assert "Enter when the 10Y-2Y Treasury spread is above 0." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_avoid_inverted_yield_curve_uses_safe_side(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Avoid risk-on entries when the yield curve is inverted."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_above",
        "symbol": "T10Y2Y",
        "threshold": 0.0,
    }
    assert "T10Y2Y" in config["reference_symbols"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_avoid_vix_above_uses_safe_side(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Avoid trading QQQ when VIX is above 30."},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 30.0,
    }
    assert config["exit_rule"] == {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "series_below",
            "symbol": "VIX",
            "threshold": 30.0,
        },
    }
    assert "VIX" in config["reference_symbols"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_unsupported_macro_symbol_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when MOVE is below 120."},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "VIX, VIX9D, VXEEM, DGS10, DGS2, T10Y2Y, and DFF" in body["message"]


def test_generate_strategy_builder_keeps_rule_symbol_reference_when_it_is_also_benchmark(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy benchmark SPY. "
                "Trade QQQ only when SPY is above its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"]["symbol"] == "SPY"
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_mixed_tradable_and_reference_sma_filters(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when QQQ is above its 50-day SMA and "
                "SPY is above its 200-day SMA."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]
    entry_rules = config["entry_rule"]["rules"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert "SPY" in config["reference_symbols"]
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert entry_rules[0] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "QQQ",
        "fast_window": 1,
        "slow_window": 50,
    }
    assert entry_rules[1] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_composite_follow_up_edits_and_sweep(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    threshold_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change RSI entry threshold to 25",
            "context": {"current_config": current_config},
        },
    )
    assert threshold_response.status_code == 200
    threshold_config = threshold_response.json()["config"]
    assert threshold_config["entry_rule"]["rules"][0]["threshold"] == 25

    sma_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change SMA filter to 150 days",
            "context": {"current_config": threshold_config},
        },
    )
    assert sma_response.status_code == 200
    sma_config = sma_response.json()["config"]
    assert sma_config["entry_rule"]["rules"][1]["slow_window"] == 150

    sweep_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try entry thresholds 20, 25, 30.",
            "context": {"current_config": sma_config},
        },
    )
    assert sweep_response.status_code == 200
    sweep_body = sweep_response.json()
    assert sweep_body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep_body["sweep_draft"]["grid"] == {
        "entry_rule.rules[0].threshold": [20, 25, 30],
    }


def test_generate_strategy_builder_follow_up_sweep_targets_entry_rsi_inside_composite_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try RSI entry thresholds 25, 30, 35.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "entry_rule.rules[0].threshold"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [25, 30, 35]}
    assert get_nested(sweep["base_config"], path) == 30

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [25, 30, 35]
    assert {variant["config"]["exit_rule"]["threshold"] for variant in variants} == {70}


def test_generate_strategy_builder_follow_up_sweep_targets_exit_rsi_inside_composite_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["exit_rule"] = {
        "kind": "group",
        "operator": "OR",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 70,
            },
            {
                "kind": "not",
                "rule": {
                    "kind": "atomic",
                    "type": "sma_above",
                    "symbol": "QQQ",
                    "fast_window": 1,
                    "slow_window": 200,
                },
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try exit RSI thresholds 65, 70, 75.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "exit_rule.rules[0].threshold"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [65, 70, 75]}
    assert get_nested(sweep["base_config"], path) == 70

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [65, 70, 75]
    assert {variant["config"]["entry_rule"]["threshold"] for variant in variants} == {30}


def test_generate_strategy_builder_follow_up_sweep_targets_sma_lookback_inside_composite_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try SMA windows 100, 150, 200.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "entry_rule.rules[1].slow_window"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [100, 150, 200]}
    assert get_nested(sweep["base_config"], path) == 200

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [100, 150, 200]
    assert {variant["config"]["entry_rule"]["rules"][1]["fast_window"] for variant in variants} == {1}
    assert {variant["config"]["entry_rule"]["rules"][0]["threshold"] for variant in variants} == {30}


def test_generate_strategy_builder_follow_up_sweep_targets_sma_inside_nested_exit_group(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["exit_rule"] = {
        "kind": "group",
        "operator": "OR",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 70,
            },
            {
                "kind": "group",
                "operator": "AND",
                "rules": [
                    {
                        "kind": "atomic",
                        "type": "sma_above",
                        "symbol": "QQQ",
                        "fast_window": 1,
                        "slow_window": 200,
                    },
                    {
                        "kind": "atomic",
                        "type": "macd_bearish_cross",
                        "symbol": "QQQ",
                    },
                ],
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try exit SMA windows 100, 150, 200.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]
    path = "exit_rule.rules[1].rules[0].slow_window"

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["grid"] == {path: [100, 150, 200]}
    assert get_nested(sweep["base_config"], path) == 200

    variants = generate_variant_configs(sweep["base_config"], sweep["grid"])
    assert [get_nested(variant["config"], path) for variant in variants] == [100, 150, 200]
    assert {variant["config"]["exit_rule"]["rules"][0]["threshold"] for variant in variants} == {70}


def test_generate_strategy_builder_follow_up_sweep_ambiguous_duplicate_indicator_returns_guidance(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["entry_rule"] = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            current_config["entry_rule"],
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try RSI thresholds 25, 30, 35.",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert "multiple possible" in body["message"]
    assert "entry/buy rule or the exit/sell rule" in body["message"]


def test_generate_strategy_builder_follow_up_sweep_missing_target_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Try SMA windows 100, 150, 200.",
            "context": {"current_config": _qqq_rsi_core_overlay_current_config()},
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["sweep_draft"] is None
    assert body["message"] == (
        "This draft does not use SMA rules yet. You can create an SMA strategy first, "
        "or ask me to replace the entry/exit rules with SMA."
    )


@pytest.mark.parametrize(
    ("prompt", "current_config", "expected_grid"),
    [
        (
            "sweep RSI entry from 25 to 40",
            _qqq_rsi_core_overlay_current_config(),
            {"entry_rule.threshold": [25, 30, 35, 40]},
        ),
        (
            "try RSI exits 60, 65, and 70",
            _qqq_rsi_core_overlay_current_config(),
            {"exit_rule.threshold": [60, 65, 70]},
        ),
        (
            "sweep VIX threshold from 15 to 30",
            _qqq_vix_rsi_current_config(),
            {"entry_rule.rules[1].threshold": [15, 20, 25, 30]},
        ),
    ],
)
def test_generate_strategy_builder_follow_up_common_sweep_prompts_validate_and_preserve_base(
    client,
    prompt,
    current_config,
    expected_grid,
):
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    sweep = body["sweep_draft"]

    assert body["response_type"] == "PARAMETER_SWEEP_DRAFT"
    assert sweep["base_config"] == original
    assert sweep["grid"] == expected_grid
    assert sweep["ranking_metric"] == "sharpe_ratio"
    assert sweep["max_variants"] == 25
    build_sweep_request(sweep)
    StrategyV2.model_validate(sweep["base_config"])


def test_generate_strategy_builder_follow_up_changes_exit_group_operator(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["exit_rule"] = {
        "kind": "group",
        "operator": "OR",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 70,
            },
            {
                "kind": "not",
                "rule": {
                    "kind": "atomic",
                    "type": "sma_above",
                    "symbol": "QQQ",
                    "fast_window": 1,
                    "slow_window": 200,
                },
            },
        ],
    }

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit from OR to AND",
            "context": {"current_config": current_config},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"
    assert body["config"]["exit_rule"]["operator"] == "AND"


def test_generate_strategy_builder_mixed_composite_operator_returns_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy. "
                "Buy when RSI is below 30 and MACD or SPY is above its 200 day SMA. "
                "Sell when RSI is above 70."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "could not deterministically parse" in body["message"].lower()


def test_generate_strategy_builder_creates_monthly_top_1_rotation(client):
    body = _post_strategy_builder_prompt(
        client,
        "Create a monthly rotation between QQQ, SPY, XLK, and TLT using 3-month momentum.",
    )

    config = body["config"]
    rotation = config["rotation"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert "allocation" not in config
    assert "entry_rule" not in config
    assert "exit_rule" not in config
    assert config["benchmark_symbol"] == "SPY"
    assert config["tradable_symbol"] == "QQQ"
    assert rotation["enabled"] is True
    assert rotation["universe"] == ["QQQ", "SPY", "XLK", "TLT"]
    assert rotation["ranking"] == {
        "type": "relative_return",
        "lookback": 63,
        "descending": True,
    }
    assert rotation["rebalance"] == {
        "frequency": "monthly",
        "day": "first_trading_day",
    }
    assert rotation["selection"]["top_n"] == 1
    assert rotation["allocation"]["weighting"] == "equal_weight"
    assert rotation["fallback"]["type"] == "cash"
    assert "Used top 1 selection by default." in body["assumptions"]


def test_generate_strategy_builder_creates_sector_top_2_21_day_rotation(client):
    body = _post_strategy_builder_prompt(
        client,
        "Create a sector rotation strategy that holds the top 2 sectors by 21-day momentum.",
    )

    rotation = body["config"]["rotation"]

    assert rotation["universe"] == ["XLK", "XLY", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE"]
    assert rotation["selection"]["top_n"] == 2
    assert rotation["ranking"]["lookback"] == 21
    assert rotation["rebalance"]["frequency"] == "monthly"


def test_generate_strategy_builder_creates_defensive_rotation_with_spy_sma200_and_cash(client):
    body = _post_strategy_builder_prompt(
        client,
        "Create a defensive rotation using QQQ, SPY, TLT, IEF, and GLD with SPY 200-day SMA risk filter and cash fallback.",
    )

    config = body["config"]
    rotation = config["rotation"]

    assert rotation["universe"] == ["QQQ", "SPY", "TLT", "IEF", "GLD"]
    assert rotation["risk_filter"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert rotation["fallback"]["type"] == "cash"
    assert "SPY" in config["reference_symbols"]


def test_generate_strategy_builder_create_prompt_with_spy_sma200_risk_filter(client):
    body = _post_strategy_builder_prompt(
        client,
        "Create a monthly rotation across QQQ, SPY, XLK, and TLT with SPY above 200-day SMA risk filter.",
    )

    rotation = body["config"]["rotation"]

    assert rotation["risk_filter"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert "No separate risk filter" not in body["summary"]


def test_generate_strategy_builder_creates_fallback_to_tlt_variant(client):
    body = _post_strategy_builder_prompt(
        client,
        "Create a top 1 monthly momentum rotation across QQQ, SPY, XLK, and TLT with fallback to TLT.",
    )

    rotation = body["config"]["rotation"]

    assert rotation["selection"]["top_n"] == 1
    assert rotation["fallback"] == {"type": "asset", "symbol": "TLT"}


def test_generate_strategy_builder_rotation_edit_lookback_from_63_to_21(client):
    current_config = _rotation_current_config()

    body = _post_strategy_builder_prompt(
        client,
        "Change rotation lookback to 21",
        current_config=current_config,
    )

    assert body["response_type"] == "UPDATE_DRAFT"
    assert body["config"]["rotation"]["ranking"]["lookback"] == 21
    assert any("rotation lookback" in change for change in body["changes"])


def test_generate_strategy_builder_rotation_edit_top_n_from_1_to_2(client):
    current_config = _rotation_current_config()

    body = _post_strategy_builder_prompt(
        client,
        "Change top_n from 1 to 2",
        current_config=current_config,
    )

    assert body["config"]["rotation"]["selection"]["top_n"] == 2
    assert any("rotation top N" in change for change in body["changes"])


def test_generate_strategy_builder_rotation_edit_fallback_from_cash_to_tlt(client):
    current_config = _rotation_current_config()

    body = _post_strategy_builder_prompt(
        client,
        "Edit fallback from cash to TLT",
        current_config=current_config,
    )

    assert body["config"]["rotation"]["fallback"] == {"type": "asset", "symbol": "TLT"}
    assert "Updated rotation fallback from cash to TLT." in body["changes"]


@pytest.mark.parametrize(
    ("prompt", "window"),
    [
        ("Add SPY SMA100 risk filter", 100),
        ("Add SPY SMA200 risk filter", 200),
        ("add SPY 200-day SMA risk filter", 200),
        ("add SPY 200 day SMA risk filter", 200),
        ("use SPY 200-day SMA as risk filter", 200),
        ("SPY above 200-day SMA risk filter", 200),
        ("add SPY 100-day SMA risk filter", 100),
    ],
)
def test_generate_strategy_builder_rotation_adds_spy_sma_risk_filter(client, prompt, window):
    current_config = _rotation_current_config()

    body = _post_strategy_builder_prompt(
        client,
        prompt,
        current_config=current_config,
    )

    assert body["config"]["rotation"]["risk_filter"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": window,
    }
    assert any("SPY above its" in change for change in body["changes"])
    assert not any("sma_above|symbol=" in change for change in body["changes"])


def test_generate_strategy_builder_rotation_combined_sma200_and_tlt_fallback_edit(client):
    current_config = _rotation_current_config()

    body = _post_strategy_builder_prompt(
        client,
        "add SPY 200-day SMA risk filter and fallback to TLT.",
        current_config=current_config,
    )

    rotation = body["config"]["rotation"]

    assert rotation["risk_filter"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert rotation["fallback"] == {"type": "asset", "symbol": "TLT"}
    assert "No separate risk filter" not in body["summary"]
    assert not any("ADD" in warning for warning in body["warnings"])
    assert "Added rotation risk filter: SPY above its 200-day SMA." in body["changes"]
    assert "Updated rotation fallback from cash to TLT." in body["changes"]
    assert not any("sma_above|symbol=" in change for change in body["changes"])


def test_generate_strategy_builder_rotation_combined_sma100_and_cash_fallback_edit(client):
    current_config = _rotation_current_config()
    current_config["rotation"]["fallback"] = {"type": "asset", "symbol": "TLT"}

    body = _post_strategy_builder_prompt(
        client,
        "use SPY 100-day SMA risk filter and fallback to cash",
        current_config=current_config,
    )

    rotation = body["config"]["rotation"]

    assert rotation["risk_filter"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 100,
    }
    assert rotation["fallback"] == {"type": "cash"}
    assert not any("USE" in warning for warning in body["warnings"])


def test_generate_strategy_builder_rotation_removes_risk_filter(client):
    current_config = _rotation_current_config()
    current_config["rotation"]["risk_filter"] = {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }

    body = _post_strategy_builder_prompt(
        client,
        "Remove risk filter",
        current_config=current_config,
    )

    assert "risk_filter" not in body["config"]["rotation"]
    assert any("rotation risk filter" in change for change in body["changes"])


def test_generate_strategy_builder_rotation_warns_and_omits_unsupported_symbol(client):
    body = _post_strategy_builder_prompt(
        client,
        "Create a monthly rotation between QQQ, SPY, XYZ, and XLK using 3-month momentum.",
    )

    assert body["config"]["rotation"]["universe"] == ["QQQ", "SPY", "XLK"]
    assert any("XYZ" in warning and "omitted" in warning for warning in body["warnings"])


def test_generate_strategy_builder_rotation_action_verbs_are_not_ticker_warnings(client):
    body = _post_strategy_builder_prompt(
        client,
        "add SPY 200-day SMA risk filter and fallback to TLT.",
        current_config=_rotation_current_config(),
    )

    joined_warnings = " ".join(body["warnings"])

    assert "ADD" not in joined_warnings
    assert "SET" not in joined_warnings
    assert "USE" not in joined_warnings


def test_generate_strategy_builder_rotation_rejects_ml_ranking_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a rotation strategy across QQQ, SPY, XLK, and TLT using an ML prediction model for ranking.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "ML prediction ranking is not supported" in body["message"]


def test_generate_strategy_builder_draft_returns_valid_strategy_v2_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a mean reversion strategy for QQQ from 2019-01-02 to 2024-12-31 "
                "with 10% stop loss"
            ),
        },
    )

    assert response.status_code == 200

    body = response.json()
    config = body["config"]

    assert config["schema_version"] == "2.0"
    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "QQQ"
    assert config["start_date"] == "2019-01-02"
    assert config["end_date"] == "2024-12-31"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["risk"]["stop_loss_pct"] == 0.1
    assert config["core_overlay"]["enabled"] is False
    assert config["core_overlay"]["core_allocation_pct"] == 0.0
    assert config["allocation"]["entry_value"] == 1.0
    assert config["allocation"]["max_position_pct"] == 1.0


def test_generate_strategy_builder_draft_accepts_optional_context(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a moving average strategy for SPY",
            "context": {
                "strategy_id": "11111111-1111-1111-1111-111111111111",
                "base_version_id": "22222222-2222-2222-2222-222222222222",
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "old-config",
                },
            },
        },
    )

    assert response.status_code == 200

    body = response.json()
    config = body["config"]
    assert config["schema_version"] == "2.0"
    assert config["tradable_symbol"] == "SPY"
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["exit_rule"]["type"] == "sma_cross_below"


def test_generate_strategy_builder_draft_excludes_unused_null_fields(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a mean reversion strategy for QQQ",
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert "fast_window" not in config["entry_rule"]
    assert "slow_window" not in config["entry_rule"]
    assert "reference_symbol" not in config["entry_rule"]
    assert "month_values" not in config["entry_rule"]


def test_generate_strategy_builder_draft_parses_benchmark_take_profit_capital_and_cooldown(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with benchmark SPY, start with 250000, "
                "take profit at 15%, and cooldown 5 bars"
            ),
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["initial_capital"] == 250000.0
    assert config["risk"]["take_profit_pct"] == 0.15
    assert config["risk"]["cooldown_bars"] == 5


def test_generate_strategy_builder_draft_parses_partial_take_profit_position_management_and_core_allocation(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with partial take profit at 10% sell 50% max 2 times, "
                "scale in to 25%, scale out to 50%, profit reduce threshold to 5%, "
                "and core allocation at 60%"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["risk"]["partial_take_profit"]["trigger_profit_pct"] == 0.10
    assert config["risk"]["partial_take_profit"]["sell_fraction_of_position"] == 0.50
    assert config["risk"]["partial_take_profit"]["max_triggers"] == 2

    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["scale_out_fraction"] == 0.50
    assert config["position_management"]["profit_reduce_threshold"] == 0.05

    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.60

    assert "take_profit_pct" not in config["risk"]


def test_generate_strategy_builder_draft_parses_scale_in_percentage(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Exit when RSI above 65. Buy 25% first."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert "scale_out_fraction" not in config["position_management"]
    assert "exit_behavior" not in config["position_management"]
    assert "profit_reduce_threshold" not in config["position_management"]
    assert "Scale in 25.0% per entry" not in body["summary"]
    assert "Enter when QQQ RSI(14) is below 35." in body["summary"]
    assert "Exit when QQQ RSI(14) is above 65." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_scale_in_only_does_not_add_scale_out_policy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Exit when RSI above 65. Scale in 25% at a time."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert "scale_out_fraction" not in config["position_management"]
    assert "exit_behavior" not in config["position_management"]
    StrategyV2.model_validate(config)


@pytest.mark.parametrize(
    ("phrase", "field", "expected"),
    [
        ("minimum trade size $1000", "minimum_trade_notional", 1000.0),
        ("skip trades under $1000", "minimum_trade_notional", 1000.0),
        ("do not trade less than $500", "minimum_trade_notional", 500.0),
        ("minimum 5 shares", "minimum_trade_shares", 5),
        ("skip trades below 1% of equity", "minimum_trade_pct_of_equity", 0.01),
        ("avoid tiny trades", "minimum_trade_notional", 1000.0),
    ],
)
def test_generate_strategy_builder_draft_parses_minimum_trade_size_controls(
    client,
    phrase,
    field,
    expected,
):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                f"Exit when RSI above 65. {phrase}."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["position_management"][field] == expected
    assert "scale_in_fraction" not in config["position_management"]
    assert "Minimum trade" in body["summary"] or "Minimum shares" in body["summary"]
    if field == "minimum_trade_pct_of_equity":
        assert config["allocation"]["entry_value"] == 1.0


def test_generate_strategy_builder_draft_warns_for_self_blocking_minimum_trade_pct(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Exit when RSI above 65. Entry size 1% of equity and skip trades below 1% of equity."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["allocation"]["entry_value"] == 0.01
    assert config["position_management"]["minimum_trade_pct_of_equity"] == 0.01
    assert any("Minimum trade size may block entries" in warning for warning in body["warnings"])


def test_generate_strategy_builder_draft_does_not_warn_for_normal_minimum_trade_pct(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Exit when RSI above 65. Entry size 2% of equity and skip trades below 1% of equity."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["allocation"]["entry_value"] == 0.02
    assert config["position_management"]["minimum_trade_pct_of_equity"] == 0.01
    assert not any("Minimum trade size may block entries" in warning for warning in body["warnings"])


def test_generate_strategy_builder_draft_parses_explicit_sell_all_exit_behavior(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Sell all when RSI is above 65."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["threshold"] == 65
    assert config["position_management"]["exit_behavior"] == "sell_all"
    assert "scale_out_fraction" not in config["position_management"]
    assert "scale_in_fraction" not in config["position_management"]
    assert "Exit behavior: sell all" not in body["summary"]
    assert "Exit when QQQ RSI(14) is above 65." in body["summary"]


def test_generate_strategy_builder_draft_sell_all_exit_behavior_has_no_visible_scale_out_fraction(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "sell all when RSI above 70"},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["threshold"] == 70.0
    assert config["position_management"]["exit_behavior"] == "sell_all"
    assert "scale_out_fraction" not in config["position_management"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_scale_out_exit_behavior_keeps_fraction(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "scale out 50% when RSI above 70"},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["threshold"] == 70.0
    assert config["position_management"]["exit_behavior"] == "scale_out"
    assert config["position_management"]["scale_out_fraction"] == 0.5
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_omits_scale_out_fraction_for_sell_all_with_scale_in(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when RSI is below 35, sell all when RSI is above 65. "
                "Scale in 25% at a time, wait 5 days between adds, max 3 entries."
            ),
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["position_management"]["exit_behavior"] == "sell_all"
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["min_bars_between_scale_ins"] == 5
    assert config["position_management"]["max_scale_in_steps"] == 3
    assert "scale_out_fraction" not in config["position_management"]


@pytest.mark.parametrize(
    "exit_phrase",
    [
        "Scale out 50%.",
        "Sell half at a time.",
        "Sell 50% each exit.",
    ],
)
def test_generate_strategy_builder_draft_parses_explicit_scale_out_exit_behavior(
    client,
    exit_phrase,
):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                f"Exit when RSI above 65. {exit_phrase}"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["position_management"]["exit_behavior"] == "scale_out"
    assert config["position_management"]["scale_out_fraction"] == 0.5
    assert "scale_in_fraction" not in config["position_management"]
    assert "Exit behavior: scale out 50.0% at a time" not in body["summary"]
    assert "Exit when QQQ RSI(14) is above 65." in body["summary"]


def test_generate_strategy_builder_follow_up_sell_all_removes_scale_out_fraction(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["exit_behavior"] = "scale_out"

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "sell all on exit",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["position_management"]["exit_behavior"] == "sell_all"
    assert "scale_out_fraction" not in config["position_management"]
    assert "Updated exit behavior from scale out to sell all." in body["changes"]


def test_generate_strategy_builder_follow_up_scale_out_adds_scale_out_fraction(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["exit_behavior"] = "sell_all"
    current_config["position_management"].pop("scale_out_fraction", None)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "sell half at a time",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["position_management"]["exit_behavior"] == "scale_out"
    assert config["position_management"]["scale_out_fraction"] == 0.5
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert "Updated exit behavior from sell all to scale out." in body["changes"]


def test_generate_strategy_builder_follow_up_explicit_scale_out_records_behavior_and_fraction_changes(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["exit_rule"]["threshold"] = 65
    current_config["position_management"] = None

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "scale out 50% when RSI is above 70",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["threshold"] == 70.0
    assert config["position_management"]["exit_behavior"] == "scale_out"
    assert config["position_management"]["scale_out_fraction"] == 0.5
    assert "scale_in_fraction" not in config["position_management"]
    assert "Updated RSI exit threshold from 65 to 70." in body["changes"]
    assert "Updated scale out fraction from none to 50.0%." in body["changes"]
    assert "Updated exit behavior from none to scale out." in body["changes"]
    assert not any("scale in" in change.lower() for change in body["changes"])
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_manual_qa_flow_scale_out_keeps_cumulative_changes(client):
    initial = _post_strategy_builder_prompt(
        client,
        "Create a QQQ mean reversion strategy with RSI below 35 and exit when RSI is above 65.",
    )
    history = _append_unique_changes([], initial["changes"])

    first_update = _post_strategy_builder_prompt(
        client,
        (
            "change RSI entry to 30\n"
            "set stop loss to 8%\n"
            "remove stop loss\n"
            "set cooldown to 5 bars\n"
            "set max position to 50%"
        ),
        current_config=initial["config"],
    )
    history = _append_unique_changes(history, first_update["changes"])

    second_update = _post_strategy_builder_prompt(
        client,
        "scale out 50% when RSI is above 70",
        current_config=first_update["config"],
    )
    history = _append_unique_changes(history, second_update["changes"])
    config = second_update["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "QQQ"
    assert config["entry_rule"]["threshold"] == 30.0
    assert config["exit_rule"]["threshold"] == 70.0
    assert config["risk"]["cooldown_bars"] == 5
    assert "stop_loss_pct" not in config["risk"]
    assert config["allocation"]["max_position_pct"] == 0.5
    assert config["position_management"]["exit_behavior"] == "scale_out"
    assert config["position_management"]["scale_out_fraction"] == 0.5
    assert "scale_in_fraction" not in config["position_management"]

    assert "Updated RSI entry threshold from 35 to 30." in history
    assert "Updated cooldown bars from 0 to 5." in history
    assert "Updated max position from 100.0% to 50.0%." in history
    assert "Updated RSI exit threshold from 65 to 70." in history
    assert "Updated exit behavior from none to scale out." in history
    assert "Updated scale out fraction from none to 50.0%." in history
    _assert_no_change_mentions(second_update["changes"], "scale in fraction")


def test_generate_strategy_builder_manual_qa_flow_allocation_min_trade_scale_in_distinction(client):
    initial = _post_strategy_builder_prompt(
        client,
        "Create a QQQ mean reversion strategy with RSI below 35 and exit when RSI is above 65.",
    )
    history = _append_unique_changes([], initial["changes"])

    update = _post_strategy_builder_prompt(
        client,
        (
            "set entry size to 25%\n"
            "set minimum trade size to 1%\n"
            "set minimum trade notional to $500\n"
            "scale in 25% at a time"
        ),
        current_config=initial["config"],
    )
    history = _append_unique_changes(history, update["changes"])
    config = update["config"]

    assert config["allocation"]["entry_value"] == 0.25
    assert config["position_management"]["minimum_trade_pct_of_equity"] == 0.01
    assert config["position_management"]["minimum_trade_notional"] == 500.0
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert "scale_out_fraction" not in config["position_management"]
    assert "exit_behavior" not in config["position_management"]
    assert config["entry_rule"]["threshold"] == 35.0
    assert config["exit_rule"]["threshold"] == 65.0
    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "QQQ"

    assert "Updated allocation from 100.0% to 25.0%." in history
    assert "Updated minimum trade percent of equity from none to 1.0%." in history
    assert "Updated minimum trade size from none to $500." in history
    assert "Updated scale in fraction from none to 25.0%." in history
    _assert_no_change_mentions(update["changes"], "scale out", "exit behavior")


def test_generate_strategy_builder_manual_qa_flow_preserves_existing_scale_in_when_scale_out(client):
    initial = _post_strategy_builder_prompt(
        client,
        "Create a QQQ mean reversion strategy with RSI below 35 and exit when RSI is above 65.",
    )
    scale_in = _post_strategy_builder_prompt(
        client,
        "scale in 25% at a time",
        current_config=initial["config"],
    )
    scale_out = _post_strategy_builder_prompt(
        client,
        "scale out 50% when RSI is above 70",
        current_config=scale_in["config"],
    )
    config = scale_out["config"]

    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["exit_behavior"] == "scale_out"
    assert config["position_management"]["scale_out_fraction"] == 0.5
    assert config["exit_rule"]["threshold"] == 70.0
    _assert_no_change_mentions(scale_out["changes"], "scale in fraction")


def test_generate_strategy_builder_manual_qa_flow_sell_all_no_scale_out_or_scale_in(client):
    initial = _post_strategy_builder_prompt(
        client,
        "Create a QQQ mean reversion strategy with RSI below 35 and exit when RSI is above 65.",
    )
    update = _post_strategy_builder_prompt(
        client,
        "sell all when RSI is above 70",
        current_config=initial["config"],
    )
    config = update["config"]

    assert config["exit_rule"]["threshold"] == 70.0
    assert config["position_management"]["exit_behavior"] == "sell_all"
    assert "scale_out_fraction" not in config["position_management"]
    assert "scale_in_fraction" not in config["position_management"]
    assert "Updated exit behavior from none to sell all." in update["changes"]
    _assert_no_change_mentions(update["changes"], "scale out fraction", "scale in fraction")


def test_generate_strategy_builder_draft_parses_max_scale_ins(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Exit when RSI above 65. Max 4 scale-ins."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["max_scale_in_steps"] == 4
    assert "Max scale-in entries: 4" not in body["summary"]
    assert "Enter when QQQ RSI(14) is below 35." in body["summary"]


def test_generate_strategy_builder_draft_parses_full_scale_in_policy_from_manual_qa_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Buy QQQ when RSI is below 35 and sell when RSI is above 65. "
                "Scale in 25% at a time, wait 3 days between adds, max 4 entries."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["min_bars_between_scale_ins"] == 3
    assert config["position_management"]["max_scale_in_steps"] == 4
    assert "Scale in 25.0% per entry" not in body["summary"]
    assert "Minimum bars between adds: 3" not in body["summary"]
    assert "Max scale-in entries: 4" not in body["summary"]
    assert "Enter when QQQ RSI(14) is below 35." in body["summary"]
    assert "Exit when QQQ RSI(14) is above 65." in body["summary"]


def test_generate_strategy_builder_draft_parses_add_up_to_scale_ins(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Exit when RSI above 65. Scale in 25% at a time and add up to 4 times."
            ),
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["max_scale_in_steps"] == 4


def test_generate_strategy_builder_draft_parses_bars_between_scale_ins(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI stays below 35. "
                "Exit when RSI rises above 65. Add 25% every 3 days while RSI stays below 35."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["min_bars_between_scale_ins"] == 3
    assert "Minimum bars between adds: 3" not in body["summary"]
    assert "Enter when QQQ RSI(14) is below 35." in body["summary"]


def test_generate_strategy_builder_follow_up_adds_scale_in_policy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "make it scale in 25% at a time, wait 5 days between adds, max 3 adds",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_sma_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["max_scale_in_steps"] == 3
    assert config["position_management"]["min_bars_between_scale_ins"] == 5
    assert "Updated scale in fraction from none to 25.0%." in body["changes"]


def test_generate_strategy_builder_follow_up_sets_max_scale_in_entries(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["min_bars_between_scale_ins"] = 3
    original_entry_rule = current_config["entry_rule"]
    original_exit_rule = current_config["exit_rule"]
    original_risk = current_config["risk"]
    original_allocation = current_config["allocation"]
    original_core_overlay = current_config["core_overlay"]
    original_reference_symbols = current_config["reference_symbols"]

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Set max scale-in entries to 4.",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["position_management"]["max_scale_in_steps"] == 4
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["min_bars_between_scale_ins"] == 3
    assert config["entry_rule"] == original_entry_rule
    assert config["exit_rule"] == original_exit_rule
    assert config["risk"] == original_risk
    assert config["allocation"] == original_allocation
    assert config["core_overlay"] == original_core_overlay
    assert config["reference_symbols"] == original_reference_symbols
    assert "No draft changes made" not in body["message"]
    assert "Updated max scale-in steps from none to 4." in body["changes"]


def test_generate_strategy_builder_follow_up_changes_max_adds(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["max_scale_in_steps"] = 4
    current_config["position_management"]["min_bars_between_scale_ins"] = 3

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Change max adds to 3.",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["position_management"]["max_scale_in_steps"] == 3
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["min_bars_between_scale_ins"] == 3
    assert "Updated max scale-in steps from 4 to 3." in body["changes"]


def test_generate_strategy_builder_follow_up_changes_scale_in_fraction(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "make it scale in 30% at a time",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_rsi_core_overlay_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["position_management"]["scale_in_fraction"] == 0.30
    assert config["position_management"]["scale_out_fraction"] == 0.5
    assert "exit_behavior" not in config["position_management"]
    assert "Updated scale in fraction from 25.0% to 30.0%." in body["changes"]


def test_generate_strategy_builder_follow_up_scale_in_only_preserves_existing_exit_behavior(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["exit_behavior"] = "sell_all"
    current_config["position_management"].pop("scale_out_fraction", None)
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "scale in 25% at a time",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["position_management"]["exit_behavior"] == "sell_all"
    assert "scale_out_fraction" not in config["position_management"]
    _assert_strategy_v2_config_preserves(
        config,
        original,
        changed_nested={"position_management": {"scale_in_fraction"}},
    )


@pytest.mark.parametrize(
    ("prompt", "expected_entry_value"),
    [
        ("Set entry size to 25%", 0.25),
        ("Change entry size to 25%", 0.25),
        ("Use 25% of equity per entry", 0.25),
        ("Buy 25% per trade", 0.25),
        ("Set allocation to 25%", 0.25),
        ("Use 50% of equity", 0.50),
    ],
)
def test_generate_strategy_builder_follow_up_changes_entry_size_without_touching_position_management(
    client,
    prompt,
    expected_entry_value,
):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["allocation"]["entry_value"] = 1.0
    current_config["position_management"]["minimum_trade_pct_of_equity"] = 0.01
    original_entry_rule = current_config["entry_rule"]
    original_exit_rule = current_config["exit_rule"]
    original_risk = current_config["risk"]
    original_core_overlay = current_config["core_overlay"]
    original_reference_symbols = current_config["reference_symbols"]
    original_scale_in_fraction = current_config["position_management"]["scale_in_fraction"]

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["allocation"]["entry_value"] == expected_entry_value
    assert config["entry_rule"] == original_entry_rule
    assert config["exit_rule"] == original_exit_rule
    assert config["risk"] == original_risk
    assert config["core_overlay"] == original_core_overlay
    assert config["reference_symbols"] == original_reference_symbols
    assert config["position_management"]["minimum_trade_pct_of_equity"] == 0.01
    assert config["position_management"]["scale_in_fraction"] == original_scale_in_fraction


def test_generate_strategy_builder_follow_up_minimum_trade_pct_preserves_entry_size(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["allocation"]["entry_value"] = 0.40

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Skip trades below 1% of equity.",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["allocation"]["entry_value"] == 0.40
    assert config["position_management"]["minimum_trade_pct_of_equity"] == 0.01
    assert config["position_management"]["scale_in_fraction"] == 0.25


@pytest.mark.parametrize(
    ("prompt", "field", "expected"),
    [
        ("minimum trade size 1%", "minimum_trade_pct_of_equity", 0.01),
        ("minimum trade notional $500", "minimum_trade_notional", 500.0),
        ("minimum shares 2", "minimum_trade_shares", 2),
    ],
)
def test_generate_strategy_builder_follow_up_minimum_trade_prompts_do_not_change_allocation(
    client,
    prompt,
    field,
    expected,
):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["allocation"]["entry_value"] = 0.40
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["position_management"][field] == expected
    _assert_strategy_v2_config_preserves(
        config,
        original,
        changed_nested={"position_management": {field}},
    )


@pytest.mark.parametrize(
    ("prompt", "expected_entry_value"),
    [
        ("entry size 25%", 0.25),
        ("allocate 30% per entry", 0.30),
    ],
)
def test_generate_strategy_builder_follow_up_entry_sizing_prompts_change_allocation_only(
    client,
    prompt,
    expected_entry_value,
):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["allocation"]["entry_value"] = 0.40
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["allocation"]["entry_value"] == expected_entry_value
    _assert_strategy_v2_config_preserves(
        config,
        original,
        changed_nested={"allocation": {"entry_value"}},
    )


def test_generate_strategy_builder_follow_up_scale_in_prompt_does_not_change_allocation(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["allocation"]["entry_value"] = 0.40
    current_config["position_management"]["scale_in_fraction"] = 0.30
    current_config["position_management"].pop("exit_behavior", None)
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "scale in 25% at a time",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert "exit_behavior" not in config["position_management"]
    assert not any("scale out" in change.lower() for change in body["changes"])
    assert not any("exit behavior" in change.lower() for change in body["changes"])
    _assert_strategy_v2_config_preserves(
        config,
        original,
        changed_nested={"position_management": {"scale_in_fraction"}},
    )


def test_generate_strategy_builder_follow_up_combined_sizing_minimum_trade_and_scale_in_only(
    client,
):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["allocation"]["entry_value"] = 0.40
    current_config["position_management"] = None
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "set entry size to 25%; set minimum trade size to 1%; "
                "set minimum trade notional to $500; scale in 25% at a time"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["allocation"]["entry_value"] == 0.25
    assert config["allocation"]["max_position_pct"] == original["allocation"]["max_position_pct"]
    assert config["position_management"] == {
        "scale_in_fraction": 0.25,
        "minimum_trade_notional": 500.0,
        "minimum_trade_pct_of_equity": 0.01,
    }
    assert config["tradable_symbol"] == original["tradable_symbol"]
    assert config["benchmark_symbol"] == original["benchmark_symbol"]
    assert config["reference_symbols"] == original["reference_symbols"]
    assert config["start_date"] == original["start_date"]
    assert config["end_date"] == original["end_date"]
    assert config["entry_rule"] == original["entry_rule"]
    assert config["exit_rule"] == original["exit_rule"]
    assert config["risk"] == StrategyV2.model_validate(original).model_dump(
        mode="json",
        exclude_none=True,
    )["risk"]
    assert config["core_overlay"] == original["core_overlay"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_follow_up_sets_minimum_trade_size(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "set minimum trade size to $1000",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_rsi_core_overlay_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["position_management"]["minimum_trade_notional"] == 1000.0
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert "Updated minimum trade size from none to $1,000." in body["changes"]


def test_generate_strategy_builder_follow_up_sets_minimum_trade_pct_and_shares(client):
    current_config = _qqq_rsi_core_overlay_current_config()

    pct_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "skip trades below 1% of equity",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )
    assert pct_response.status_code == 200
    pct_config = pct_response.json()["config"]
    assert pct_config["position_management"]["minimum_trade_pct_of_equity"] == 0.01

    shares_response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "minimum 5 shares",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )
    assert shares_response.status_code == 200
    shares_config = shares_response.json()["config"]
    assert shares_config["position_management"]["minimum_trade_shares"] == 5


def test_generate_strategy_builder_follow_up_removes_minimum_trade_size(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["minimum_trade_notional"] = 1000.0
    current_config["position_management"]["minimum_trade_pct_of_equity"] = 0.01
    current_config["position_management"]["minimum_trade_shares"] = 5

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove minimum trade size",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert "minimum_trade_notional" not in config["position_management"]
    assert "minimum_trade_pct_of_equity" not in config["position_management"]
    assert "minimum_trade_shares" not in config["position_management"]
    assert "Updated minimum trade size from $1,000 to none." in body["changes"]


def test_generate_strategy_builder_follow_up_removes_scale_in_limit(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["max_scale_in_steps"] = 4

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove scale-in limit",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert "max_scale_in_steps" not in config["position_management"]
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert "Updated max scale-in steps from 4 to none." in body["changes"]


def test_generate_strategy_builder_follow_up_waits_between_adds(client):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["position_management"]["max_scale_in_steps"] = 4
    original_entry_rule = current_config["entry_rule"]
    original_exit_rule = current_config["exit_rule"]

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Wait 5 days between adds.",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["position_management"]["min_bars_between_scale_ins"] == 5
    assert config["position_management"]["max_scale_in_steps"] == 4
    assert config["position_management"]["scale_in_fraction"] == 0.25
    assert config["entry_rule"] == original_entry_rule
    assert config["exit_rule"] == original_exit_rule
    assert "Updated minimum bars between scale-ins from 0 to 5." in body["changes"]


def test_generate_strategy_builder_follow_up_turns_off_scale_in_controls(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "turn off scale-in controls",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_rsi_core_overlay_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert "position_management" not in config or config["position_management"] is None
    assert "Updated scale in fraction from 25.0% to none." in body["changes"]


def test_generate_strategy_builder_draft_warns_on_invalid_scale_in_values(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create an RSI strategy for QQQ. Enter when RSI below 35. "
                "Exit when RSI above 65. Scale in 150%, max 0 entries, "
                "and wait -2 bars between adds."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert "position_management" not in config or config["position_management"] is None
    assert "Scale-in percentage must be greater than 0% and no more than 100%; ignored that value." in body["warnings"]
    assert "Max scale-ins must be a positive whole number; ignored that value." in body["warnings"]
    assert "Minimum bars between adds must be 0 or greater; ignored that value." in body["warnings"]


def test_generate_strategy_builder_existing_vix_rsi_prompt_still_works(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Only trade QQQ when VIX is below 25 and RSI is below 35."},
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["reference_symbols"] == ["VIX"]
    assert config["entry_rule"]["kind"] == "group"
    assert any(rule.get("type") == "rsi_below" for rule in config["entry_rule"]["rules"])
    assert any(rule.get("type") == "series_below" for rule in config["entry_rule"]["rules"])


@pytest.mark.parametrize("prompt", WORKSPACE_SAMPLE_PROMPTS)
def test_workspace_sample_prompts_compile_to_supported_strategy_v2_drafts(client, prompt):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] in {"CREATE_DRAFT", "UPDATE_DRAFT"}
    assert body["config"] is not None
    config = body["config"]

    StrategyV2.model_validate(config)
    _assert_strategy_config_uses_supported_symbols(config)


def test_generate_strategy_builder_exact_xle_rsi_prompt_parses_cooldown_and_max_position(client):
    prompt = (
        "Create an XLE RSI pullback strategy with RSI below 45, exit above 60, "
        "12% stop loss, 5-bar cooldown, and max position 75%."
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "XLE"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "XLE",
        "lookback": 14,
        "threshold": 45.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "XLE",
        "lookback": 14,
        "threshold": 60.0,
    }
    assert config["risk"]["stop_loss_pct"] == 0.12
    assert config["risk"]["cooldown_bars"] == 5
    assert config["allocation"]["max_position_pct"] == 0.75
    assert "Stop loss set to 12.0%." in body["summary"]
    assert "Cooldown set to 5 bars." in body["summary"]
    assert "Max position set to 75.0%." in body["summary"]
    assert "cooldown 0 bars" not in body["summary"].lower()
    assert "Used cooldown of 0 bars by default." not in body["assumptions"]


@pytest.mark.parametrize(
    "cooldown_phrase",
    [
        "5-bar cooldown",
        "5 bar cooldown",
        "cooldown 5 bars",
        "set cooldown to 5 bars",
        "wait 5 bars before re-entering",
    ],
)
def test_generate_strategy_builder_draft_parses_cooldown_phrase_variants(
    client,
    cooldown_phrase,
):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ RSI strategy with RSI below 30, exit above 70, "
                f"and {cooldown_phrase}."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    assert body["config"]["risk"]["cooldown_bars"] == 5


@pytest.mark.parametrize(
    "prompt",
    [
        "5-bar cooldown",
        "5 bar cooldown",
        "cooldown 5 bars",
        "set cooldown to 5 bars",
        "wait 5 bars before re-entering",
    ],
)
def test_generate_strategy_builder_follow_up_sets_cooldown_phrase_variants(
    client,
    prompt,
):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["risk"]["take_profit_pct"] = 0.2
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["risk"]["cooldown_bars"] == 5
    _assert_strategy_v2_config_preserves(
        config,
        original,
        changed_top_level=set(),
        changed_nested={"risk": {"cooldown_bars"}},
    )


@pytest.mark.parametrize("prompt", ["remove cooldown", "no cooldown"])
def test_generate_strategy_builder_follow_up_removes_cooldown_without_touching_unrelated_config(
    client,
    prompt,
):
    current_config = _qqq_rsi_core_overlay_current_config()
    current_config["risk"]["cooldown_bars"] = 5
    current_config["risk"]["take_profit_pct"] = 0.2
    original = copy.deepcopy(current_config)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": current_config,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["risk"]["cooldown_bars"] == 0
    _assert_strategy_v2_config_preserves(
        config,
        original,
        changed_top_level=set(),
        changed_nested={"risk": {"cooldown_bars"}},
    )


def test_workspace_sample_prompt_set_keeps_major_and_defensive_examples():
    prompt_text = "\n".join(
        param.values[0] for param in WORKSPACE_SAMPLE_PROMPTS
    )
    prompt_text_lower = prompt_text.lower()

    assert "QQQ" in prompt_text
    assert "SPY" in prompt_text
    assert "risk-control" in prompt_text_lower or "defensive" in prompt_text_lower


def test_generate_strategy_builder_draft_parses_core_overlay_prompt(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy from 2018-01-02 to 2026-04-24.\n"
                "Core overlay enabled.\n"
                "Core allocation 60%.\n"
                "Overlay allocation 40%.\n"
                "Core: Always hold QQQ.\n"
                "Overlay: Buy QQQ when RSI 14 is below 30.\n"
                "Sell QQQ when RSI 14 is above 70.\n"
                "Benchmark QQQ.\n"
                "Initial capital 100000.\n"
                "Transaction cost 5 bps."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert "could not convert string to float" not in body["message"]
    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.60
    assert config["allocation"]["entry_value"] == 0.40
    assert config["allocation"]["max_position_pct"] == 0.40
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70.0,
    }
    assert "Core allocation set to 60.0%." in body["summary"]
    assert "Overlay allocation set to 40.0%." in body["summary"]


def test_generate_strategy_builder_draft_parses_core_overlay_natural_language_prompt(client):
    prompt = (
        "Create a QQQ core-overlay strategy from 2018-01-02 to 2026-04-24. "
        "Use 60% always-invested core allocation in QQQ. "
        "Use the remaining 40% as a tactical overlay:\n"
        "- Enter the overlay when QQQ RSI(14) falls below 30\n"
        "- Exit the overlay when QQQ RSI(14) rises above 70\n"
        "Use QQQ as the benchmark, $100,000 initial capital, and 5 bps transaction cost."
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert "could not convert string to float" not in body["message"]
    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "QQQ"
    assert config["start_date"] == "2018-01-02"
    assert config["end_date"] == "2026-04-24"
    assert config["initial_capital"] == 100000.0
    assert config["transaction_cost_bps"] == 5.0
    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.60
    assert config["allocation"]["entry_value"] == 0.40
    assert config["allocation"]["max_position_pct"] == 0.40
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30.0,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70.0,
    }


def test_generate_strategy_builder_draft_parses_transaction_cost_and_max_position(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for QQQ with transaction cost at 12 bps and max position at 40%",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["transaction_cost_bps"] == 12.0
    assert config["allocation"]["max_position_pct"] == 0.40


def test_generate_strategy_builder_draft_parses_custom_moving_average_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a moving average strategy for SPY using 10-day SMA crosses above 30-day SMA",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["entry_rule"]["fast_window"] == 10
    assert config["entry_rule"]["slow_window"] == 30
    assert config["exit_rule"]["fast_window"] == 10
    assert config["exit_rule"]["slow_window"] == 30
    assert "SPY 10-day SMA crosses above SPY 30-day SMA" in body["summary"]
    assert "SPY price is above its 30-day SMA" not in body["summary"]


def test_generate_strategy_builder_draft_parses_sma_above_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a 20/50 SMA above strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "sma_above"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["fast_window"] == 20
    assert config["entry_rule"]["slow_window"] == 50

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "sma_above"
    assert config["exit_rule"]["rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["rule"]["fast_window"] == 20
    assert config["exit_rule"]["rule"]["slow_window"] == 50


def test_generate_strategy_builder_draft_parses_macd_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a MACD strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "macd_bullish_cross"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"


def test_generate_strategy_builder_draft_parses_kd_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a KD strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["type"] == "kd_dead_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"


def test_generate_strategy_builder_draft_parses_stochastic_strategy_as_kd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a stochastic strategy for QQQ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["type"] == "kd_dead_cross"


def test_generate_strategy_builder_draft_parses_seasonality_strategy_single_month(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a seasonality strategy for QQQ in November",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "month_in"
    assert config["entry_rule"]["month_values"] == [11]
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "month_in"
    assert config["exit_rule"]["rule"]["month_values"] == [11]


def test_generate_strategy_builder_draft_parses_seasonality_strategy_multiple_months(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a month strategy for SPY in November and December",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "SPY"
    assert config["entry_rule"]["type"] == "month_in"
    assert config["entry_rule"]["month_values"] == [11, 12]
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "month_in"
    assert config["exit_rule"]["rule"]["month_values"] == [11, 12]


def test_generate_strategy_builder_draft_parses_relative_strength_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a relative strength strategy for QQQ versus SPY over 20 days with 3% threshold",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "relative_return_above"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["reference_symbol"] == "SPY"
    assert config["entry_rule"]["lookback"] == 20
    assert config["entry_rule"]["threshold"] == 0.03
    assert "SPY" in config["reference_symbols"]

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "relative_return_above"
    assert config["exit_rule"]["rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["rule"]["reference_symbol"] == "SPY"
    assert config["exit_rule"]["rule"]["lookback"] == 20
    assert config["exit_rule"]["rule"]["threshold"] == 0.03
    assert (
        "Enter when QQQ outperforms SPY by more than 3.0% over 20 trading days."
        in body["summary"]
    )
    assert (
        "Exit when QQQ no longer outperforms SPY by more than 3.0% over 20 trading days."
        in body["summary"]
    )
    assert (
        "Interpreted relative strength language as QQQ outperforming SPY over 20 trading days."
        in body["assumptions"]
    )

    dates = pd.date_range("2021-01-04", periods=21, freq="B")

    def frame(symbol: str, closes: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": dates,
                "symbol": symbol,
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [1_000_000.0] * len(closes),
                "vwap": closes,
                "transactions": [1_000.0] * len(closes),
            }
        )

    strategy = StrategyV2.model_validate(config)
    bundle = MarketDataBundle(
        tradable=frame("QQQ", [100.0] * 20 + [108.0]),
        references={"SPY": frame("SPY", [100.0] * 20 + [104.0])},
    )
    enriched = enrich_market_data(bundle, strategy)

    assert evaluate_rule(strategy.entry_rule, enriched, 20, strategy.tradable_symbol) is True


def test_generate_strategy_builder_draft_parses_realized_volatility_below_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Buy QQQ when 20-day volatility is below 25%.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["type"] == "realized_volatility_below"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["lookback"] == 20
    assert config["entry_rule"]["threshold"] == 0.25
    assert "Enter when QQQ 20-day realized volatility is below 25.0%." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_parses_realized_volatility_above_with_default_lookback(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Sell when volatility is above 35%.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["exit_rule"]["type"] == "realized_volatility_above"
    assert config["exit_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["lookback"] == 20
    assert config["exit_rule"]["threshold"] == 0.35
    assert "Used 20 trading days as the realized volatility lookback by default." in body["assumptions"]
    assert "Exit when QQQ 20-day realized volatility is above 35.0%." in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_parses_composite_rsi_and_volatility_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy that buys when RSI is below 30 and 20-day volatility is below 25%. "
                "Sell when RSI is above 70 or 20-day volatility is above 35%."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "realized_volatility_below"
    assert config["entry_rule"]["rules"][1]["lookback"] == 20
    assert config["entry_rule"]["rules"][1]["threshold"] == 0.25
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1]["type"] == "realized_volatility_above"
    assert config["exit_rule"]["rules"][1]["lookback"] == 20
    assert config["exit_rule"]["rules"][1]["threshold"] == 0.35
    assert "QQQ 20-day realized volatility is below 25.0%" in body["summary"]
    assert "QQQ 20-day realized volatility is above 35.0%" in body["summary"]
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_exact_realized_volatility_prompt_validates(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a QQQ strategy that buys when 20-day volatility is below 25%. "
                "Sell when 20-day volatility is above 35%."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "realized_volatility_below",
        "symbol": "QQQ",
        "lookback": 20,
        "threshold": 0.25,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "realized_volatility_above",
        "symbol": "QQQ",
        "lookback": 20,
        "threshold": 0.35,
    }
    StrategyV2.model_validate(config)


def test_generate_strategy_builder_draft_syncs_reference_symbols_for_relative_strength_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a relative strength strategy for QQQ versus TLT over 60 days with 5% threshold",
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["reference_symbols"] == ["TLT"]


def test_generate_strategy_builder_draft_parses_composite_entry_and_exit_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when RSI below 30 and MACD "
                "and exit when RSI above 70 or MACD"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert len(config["entry_rule"]["rules"]) == 2
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert len(config["exit_rule"]["rules"]) == 2
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_parses_composite_rule_with_sma_above_clause(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when 20 day SMA is above 50 day SMA and MACD "
                "and exit when RSI above 70"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "sma_above"
    assert config["entry_rule"]["rules"][0]["fast_window"] == 20
    assert config["entry_rule"]["rules"][0]["slow_window"] == 50
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_parses_window_entry_and_exit_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when any RSI below 30 within 5 bars "
                "and exit when all RSI above 70 within 3 bars"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["mode"] == "ANY"
    assert config["entry_rule"]["window_bars"] == 5
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["rule"]["threshold"] == 30

    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["mode"] == "ALL"
    assert config["exit_rule"]["window_bars"] == 3
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["rule"]["threshold"] == 70


def test_generate_strategy_builder_draft_parses_sequence_entry_and_exit_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "Create a strategy for QQQ with entry when RSI below 30 then MACD within 5 bars "
                "and exit when RSI above 70 then MACD within 4 bars"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"

    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["window_bars"] == 5
    assert len(config["entry_rule"]["steps"]) == 2
    assert config["entry_rule"]["steps"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["steps"][0]["threshold"] == 30
    assert config["entry_rule"]["steps"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "sequence"
    assert config["exit_rule"]["window_bars"] == 4
    assert len(config["exit_rule"]["steps"]) == 2
    assert config["exit_rule"]["steps"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["steps"][0]["threshold"] == 70
    assert config["exit_rule"]["steps"][1]["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_parses_using_symbol_as_benchmark_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for QQQ using TLT as benchmark",
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "TLT"


def test_generate_strategy_builder_draft_uses_current_config_as_base_for_new_version(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Tighten stop loss to 8% and change benchmark to SPY",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-below-to-rsi-above",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.1,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["start_date"] == "2019-01-02"
    assert config["end_date"] == "2024-12-31"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_applies_sequential_rsi_entry_edit_from_current_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change RSI entry to 25",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                    "position_management": {
                        "scale_in_fraction": 0.25,
                        "scale_out_fraction": 0.5,
                        "profit_reduce_threshold": 0.05,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["threshold"] == 25
    assert config["exit_rule"]["threshold"] == 70
    assert "Updated RSI entry threshold from 30 to 25." in body["changes"]
    assert not any("3000.0%" in change or "2500.0%" in change for change in body["changes"])
    assert not any("relative strength threshold" in change for change in body["changes"])


@pytest.mark.parametrize(
    "prompt",
    [
        "change entry threshold to 25",
        "change the entry threshold to 25",
        "set entry threshold to 25",
        "update entry threshold to 25",
    ],
)
def test_generate_strategy_builder_draft_applies_plain_entry_threshold_edit_from_current_config(client, prompt):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_rsi_core_overlay_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 25,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70,
    }
    assert config["allocation"] == {
        "entry_mode": "percent_of_equity",
        "entry_value": 0.4,
        "max_position_pct": 0.4,
    }
    assert config["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.6,
    }
    assert "Updated RSI entry threshold from 30 to 25." in body["changes"]
    assert "Unsupported edit type" not in body["message"]


def test_generate_strategy_builder_draft_applies_sequential_rsi_exit_edit_from_current_config(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change RSI exit to 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                    "position_management": {
                        "scale_in_fraction": 0.25,
                        "scale_out_fraction": 0.5,
                        "profit_reduce_threshold": 0.05,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08
    assert config["entry_rule"]["threshold"] == 30
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["threshold"] == 65


@pytest.mark.parametrize(
    "prompt",
    [
        "change exit threshold to 65",
        "set exit threshold to 65",
    ],
)
def test_generate_strategy_builder_draft_applies_plain_exit_threshold_edit_from_current_config(client, prompt):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": prompt,
            "context": {
                "mode": "NEW_VERSION",
                "current_config": _qqq_rsi_core_overlay_current_config(),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 30,
    }
    assert config["exit_rule"] == {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 65,
    }
    assert config["allocation"] == {
        "entry_mode": "percent_of_equity",
        "entry_value": 0.4,
        "max_position_pct": 0.4,
    }
    assert config["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.6,
    }
    assert "Updated RSI exit threshold from 70 to 65." in body["changes"]
    assert "Unsupported edit type" not in body["message"]


def test_generate_strategy_builder_draft_switches_existing_strategy_to_macd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "macd_bullish_cross"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_changes_tradable_symbol_and_rewrites_atomic_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change tradable symbol to SPY",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["tradable_symbol"] == "SPY"
    assert config["benchmark_symbol"] == "SPY"
    assert config["entry_rule"]["symbol"] == "SPY"
    assert config["exit_rule"]["symbol"] == "SPY"
    assert config["name"].startswith("spy-")
    assert "Updated tradable symbol from QQQ to SPY." in body["changes"]


def test_generate_strategy_builder_draft_switches_existing_strategy_to_sma_above(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to 10/30 SMA above",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "sma_above"
    assert config["entry_rule"]["fast_window"] == 10
    assert config["entry_rule"]["slow_window"] == 30

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "sma_above"
    assert config["exit_rule"]["rule"]["fast_window"] == 10
    assert config["exit_rule"]["rule"]["slow_window"] == 30


def test_generate_strategy_builder_draft_switches_existing_strategy_to_kd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["type"] == "kd_dead_cross"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_switches_existing_strategy_to_seasonality(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to seasonality in November",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "month_in"
    assert config["entry_rule"]["month_values"] == [11]
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "month_in"
    assert config["exit_rule"]["rule"]["month_values"] == [11]
    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_switches_existing_strategy_to_relative_strength(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to relative strength versus SPY over 20 days with 3% threshold",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["type"] == "relative_return_above"
    assert config["entry_rule"]["symbol"] == "QQQ"
    assert config["entry_rule"]["reference_symbol"] == "SPY"
    assert config["entry_rule"]["lookback"] == 20
    assert config["entry_rule"]["threshold"] == 0.03

    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["type"] == "relative_return_above"
    assert config["exit_rule"]["rule"]["symbol"] == "QQQ"
    assert config["exit_rule"]["rule"]["reference_symbol"] == "SPY"
    assert config["exit_rule"]["rule"]["lookback"] == 20
    assert config["exit_rule"]["rule"]["threshold"] == 0.03

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_generate_strategy_builder_draft_switches_existing_strategy_to_composite_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "change this strategy to entry when RSI below 25 and MACD "
                "and exit when RSI above 65 or MACD"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][0]["threshold"] == 25
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "OR"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][0]["threshold"] == 65
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"

    assert config["benchmark_symbol"] == "SPY"
    assert config["risk"]["stop_loss_pct"] == 0.08
    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_updates_entry_group_operator(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry group operator to or",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "OR"
    assert config["exit_rule"]["operator"] == "OR"
    assert "Updated entry group operator from AND to OR." in body["changes"]


def test_generate_strategy_builder_draft_updates_entry_group_second_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second condition of entry group to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "kd_golden_cross"
    assert "Updated entry group second condition" in " ".join(body["changes"])


def test_generate_strategy_builder_draft_updates_exit_group_first_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change first condition of exit group to RSI above 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][0]["threshold"] == 65
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"
    assert "Updated exit group first condition" in " ".join(body["changes"])


def test_generate_strategy_builder_draft_removes_second_condition_of_entry_group(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove second condition of entry group",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "group"
    assert any("Updated entry rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_first_condition_of_exit_group(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove first condition of exit group",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "OR",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["kind"] == "group"
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_switches_existing_strategy_to_window_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "change this strategy to entry when any RSI below 25 within 5 bars "
                "and exit when all RSI above 65 within 3 bars"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["mode"] == "ANY"
    assert config["entry_rule"]["window_bars"] == 5
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["rule"]["threshold"] == 25

    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["mode"] == "ALL"
    assert config["exit_rule"]["window_bars"] == 3
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["rule"]["threshold"] == 65

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_updates_entry_window_bars_and_mode(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry window to 10 bars and change entry window mode to all",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["window_bars"] == 10
    assert config["entry_rule"]["mode"] == "ALL"
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"

    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["window_bars"] == 3
    assert config["exit_rule"]["mode"] == "ALL"

    assert "Updated entry window bars from 5 to 10." in body["changes"]
    assert "Updated entry window mode from ANY to ALL." in body["changes"]


def test_generate_strategy_builder_draft_updates_exit_window_bars(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit window to 6 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["window_bars"] == 6
    assert config["exit_rule"]["mode"] == "ALL"
    assert "Updated exit window bars from 3 to 6." in body["changes"]


def test_generate_strategy_builder_draft_updates_entry_window_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry window inner rule to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["rule"]["type"] == "kd_golden_cross"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert "Updated entry window inner rule" in " ".join(body["changes"])


def test_generate_strategy_builder_draft_updates_exit_not_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit not inner rule to RSI above 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "sma_above",
                            "symbol": "QQQ",
                            "fast_window": 20,
                            "slow_window": 50,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["rule"]["threshold"] == 65
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_exit_not_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove exit not wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "sma_above",
                            "symbol": "QQQ",
                            "fast_window": 20,
                            "slow_window": 50,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "sma_above"
    assert config["exit_rule"]["fast_window"] == 20
    assert config["exit_rule"]["slow_window"] == 50
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_entry_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove entry window wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ALL",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "window"
    assert any("Updated entry rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_switches_existing_strategy_to_sequence_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "change this strategy to entry when RSI below 25 then MACD within 5 bars "
                "and exit when RSI above 65 then MACD within 4 bars"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["window_bars"] == 5
    assert config["entry_rule"]["steps"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["steps"][0]["threshold"] == 25
    assert config["entry_rule"]["steps"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "sequence"
    assert config["exit_rule"]["window_bars"] == 4
    assert config["exit_rule"]["steps"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["steps"][0]["threshold"] == 65
    assert config["exit_rule"]["steps"][1]["type"] == "macd_bearish_cross"

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_updates_entry_sequence_bars(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry sequence to 8 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["window_bars"] == 8
    assert config["entry_rule"]["steps"][1]["type"] == "macd_bullish_cross"
    assert "Updated entry sequence bars from 5 to 8." in body["changes"]


def test_generate_strategy_builder_draft_updates_entry_sequence_second_step_to_kd(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second step of entry sequence to KD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "sequence"
    assert config["entry_rule"]["steps"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["steps"][1]["type"] == "kd_golden_cross"
    assert "Updated entry sequence second step from macd_bullish_cross|symbol=QQQ to kd_golden_cross|symbol=QQQ." in body["changes"]


def test_generate_strategy_builder_draft_removes_second_step_of_entry_sequence(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove second step of entry sequence",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["exit_rule"]["kind"] == "sequence"
    assert any("Updated entry rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_first_step_of_exit_sequence(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove first step of exit sequence",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "sequence",
                        "window_bars": 5,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "macd_bearish_cross"
    assert config["entry_rule"]["kind"] == "sequence"
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_changes_tradable_symbol_and_rewrites_nested_rules(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change this strategy to IWM",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 5,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bullish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["tradable_symbol"] == "IWM"
    assert config["benchmark_symbol"] == "SPY"

    entry_group_rules = config["entry_rule"]["rule"]["rules"]
    assert entry_group_rules[0]["symbol"] == "IWM"
    assert entry_group_rules[1]["symbol"] == "IWM"

    exit_steps = config["exit_rule"]["steps"]
    assert exit_steps[0]["symbol"] == "IWM"
    assert exit_steps[1]["symbol"] == "IWM"

    assert "Updated tradable symbol from QQQ to IWM." in body["changes"]


def test_generate_strategy_builder_draft_updates_nested_relative_strength_rule_and_syncs_reference_symbols(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength reference to TLT and set relative strength threshold to 5%",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": ["GLD"],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "relative_return_above",
                                "symbol": "QQQ",
                                "reference_symbol": "GLD",
                                "lookback": 20,
                                "threshold": 0.03,
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "relative_return_above",
                                "symbol": "QQQ",
                                "reference_symbol": "GLD",
                                "lookback": 20,
                                "threshold": 0.03,
                            },
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    entry_relative_rule = config["entry_rule"]["rules"][1]
    exit_relative_rule = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert entry_relative_rule["reference_symbol"] == "TLT"
    assert entry_relative_rule["threshold"] == 0.05
    assert exit_relative_rule["reference_symbol"] == "TLT"
    assert exit_relative_rule["threshold"] == 0.05
    assert config["reference_symbols"] == ["TLT"]


def test_generate_strategy_builder_draft_adds_macd_confirmation_to_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["operator"] == "AND"
    assert len(config["entry_rule"]["rules"]) == 2
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["operator"] == "AND"
    assert len(config["exit_rule"]["rules"]) == 2
    assert config["exit_rule"]["rules"][0]["type"] == "rsi_above"
    assert config["exit_rule"]["rules"][1]["type"] == "macd_bearish_cross"

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_removes_macd_confirmation_from_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-with-macd-confirmation",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["entry_rule"]["kind"] == "atomic"
    assert config["entry_rule"]["type"] == "rsi_below"
    assert config["entry_rule"]["threshold"] == 30

    assert config["exit_rule"]["kind"] == "atomic"
    assert config["exit_rule"]["type"] == "rsi_above"
    assert config["exit_rule"]["threshold"] == 70

    assert any("Updated entry rule" in change for change in body["changes"])
    assert any("Updated exit rule" in change for change in body["changes"])


def test_generate_strategy_builder_draft_adds_kd_confirmation_to_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add KD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][1]["type"] == "kd_golden_cross"

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["rules"][1]["type"] == "kd_dead_cross"


def test_generate_strategy_builder_draft_adds_relative_strength_confirmation_to_existing_strategy(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add relative strength confirmation versus TLT over 60 days with 5% threshold",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][1]["type"] == "relative_return_above"
    assert config["entry_rule"]["rules"][1]["reference_symbol"] == "TLT"
    assert config["entry_rule"]["rules"][1]["lookback"] == 60
    assert config["entry_rule"]["rules"][1]["threshold"] == 0.05

    assert config["exit_rule"]["kind"] == "group"
    assert config["exit_rule"]["rules"][1]["type"] == "relative_return_above"
    assert config["exit_rule"]["rules"][1]["reference_symbol"] == "TLT"
    assert config["exit_rule"]["rules"][1]["lookback"] == 60
    assert config["exit_rule"]["rules"][1]["threshold"] == 0.05


def test_generate_strategy_builder_draft_updates_seasonality_months_and_records_change(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change months to January and February",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-month-in-to-not-month-in",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "month_in",
                        "month_values": [11],
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "month_in",
                            "month_values": [11],
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["month_values"] == [1, 2]
    assert config["exit_rule"]["rule"]["month_values"] == [1, 2]
    assert "Updated seasonality months from 11 to 1, 2." in body["changes"]


def test_generate_strategy_builder_draft_updates_relative_strength_reference_symbol(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength reference to TLT",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "QQQ",
                        "reference_symbol": "SPY",
                        "lookback": 20,
                        "threshold": 0.03,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "relative_return_above",
                            "symbol": "QQQ",
                            "reference_symbol": "SPY",
                            "lookback": 20,
                            "threshold": 0.03,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["reference_symbol"] == "TLT"
    assert config["exit_rule"]["rule"]["reference_symbol"] == "TLT"
    assert "Updated relative strength reference symbol from SPY to TLT." in body["changes"]


def test_generate_strategy_builder_draft_updates_relative_strength_lookback(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength lookback to 60",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "QQQ",
                        "reference_symbol": "SPY",
                        "lookback": 20,
                        "threshold": 0.03,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "relative_return_above",
                            "symbol": "QQQ",
                            "reference_symbol": "SPY",
                            "lookback": 20,
                            "threshold": 0.03,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["lookback"] == 60
    assert config["exit_rule"]["rule"]["lookback"] == 60
    assert "Updated relative strength lookback from 20 to 60." in body["changes"]


def test_generate_strategy_builder_draft_updates_relative_strength_threshold(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change relative strength threshold to 5%",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-relative-strength-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "relative_return_above",
                        "symbol": "QQQ",
                        "reference_symbol": "SPY",
                        "lookback": 20,
                        "threshold": 0.03,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "relative_return_above",
                            "symbol": "QQQ",
                            "reference_symbol": "SPY",
                            "lookback": 20,
                            "threshold": 0.03,
                        },
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["threshold"] == 0.05
    assert config["exit_rule"]["rule"]["threshold"] == 0.05
    assert "Updated relative strength threshold from 3.0% to 5.0%." in body["changes"]


def test_generate_strategy_builder_draft_applies_sequential_stop_loss_take_profit_allocation_benchmark_and_cooldown_edits(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change stop loss to 6%, change take profit to 18%, change allocation to 40%, change benchmark to TLT, and change cooldown to 3 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "take_profit_pct": 0.12,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert config["benchmark_symbol"] == "TLT"
    assert config["allocation"]["entry_value"] == 0.4
    assert config["risk"]["stop_loss_pct"] == 0.06
    assert config["risk"]["take_profit_pct"] == 0.18
    assert config["risk"]["cooldown_bars"] == 3
    assert "Updated stop loss from 8.0% to 6.0%." in body["changes"]
    assert "Updated take profit from 12.0% to 18.0%." in body["changes"]
    assert "Updated allocation from 100.0% to 40.0%." in body["changes"]
    assert "Updated benchmark from SPY to TLT." in body["changes"]
    assert "Updated cooldown bars from 0 to 3." in body["changes"]



def test_generate_strategy_builder_draft_can_remove_stop_loss_take_profit_and_cooldown(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove stop loss, remove take profit, and remove cooldown",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "take_profit_pct": 0.15,
                        "cooldown_bars": 5,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert "stop_loss_pct" not in config["risk"]
    assert "take_profit_pct" not in config["risk"]
    assert config["risk"]["cooldown_bars"] == 0
    assert "Updated stop loss from 8.0% to none." in body["changes"]
    assert "Updated take profit from 15.0% to none." in body["changes"]
    assert "Updated cooldown bars from 5 to 0." in body["changes"]


def test_generate_strategy_builder_draft_updates_partial_take_profit_position_management_and_core_allocation(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": (
                "add partial take profit at 12% sell 40% max 3 times, "
                "set scale in to 30%, set scale out to 60%, "
                "set profit reduce threshold to 7%, and enable core allocation at 55%"
            ),
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                    "position_management": None,
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"

    assert config["risk"]["partial_take_profit"]["trigger_profit_pct"] == 0.12
    assert config["risk"]["partial_take_profit"]["sell_fraction_of_position"] == 0.40
    assert config["risk"]["partial_take_profit"]["max_triggers"] == 3

    assert config["position_management"]["scale_in_fraction"] == 0.30
    assert config["position_management"]["scale_out_fraction"] == 0.60
    assert config["position_management"]["profit_reduce_threshold"] == 0.07

    assert config["core_overlay"]["enabled"] is True
    assert config["core_overlay"]["core_allocation_pct"] == 0.55

    assert "Updated partial take profit trigger from none to 12.0%." in body["changes"]
    assert "Updated scale in fraction from none to 30.0%." in body["changes"]
    assert "Updated core allocation from disabled to enabled." in body["changes"]


def test_generate_strategy_builder_draft_updates_transaction_cost_and_max_position(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change transaction cost to 9 bps and set max position to 35%",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["transaction_cost_bps"] == 9.0
    assert config["allocation"]["max_position_pct"] == 0.35
    assert "Updated transaction cost from 5 to 9.0." in body["changes"]
    assert "Updated max position from 100.0% to 35.0%." in body["changes"]


def test_generate_strategy_builder_draft_can_remove_partial_take_profit_position_management_and_core_allocation(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove partial take profit, remove position management, and disable core allocation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-managed-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "stop_loss_pct": 0.08,
                        "partial_take_profit": {
                            "trigger_profit_pct": 0.10,
                            "sell_fraction_of_position": 0.50,
                            "max_triggers": 2,
                        },
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": True,
                        "core_allocation_pct": 0.60,
                    },
                    "position_management": {
                        "scale_in_fraction": 0.25,
                        "scale_out_fraction": 0.50,
                        "profit_reduce_threshold": 0.05,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert "partial_take_profit" not in config["risk"]
    assert "position_management" not in config or config["position_management"] is None
    assert config["core_overlay"]["enabled"] is False
    assert config["core_overlay"]["core_allocation_pct"] == 0.0

    assert "Updated partial take profit trigger from 10.0% to none." in body["changes"]
    assert "Updated scale in fraction from 25.0% to none." in body["changes"]
    assert "Updated core allocation from enabled to disabled." in body["changes"]


def test_generate_strategy_builder_returns_answer_for_info_question(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What ETF symbols are currently supported?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert "Supported ETF symbols" in body["message"]


def test_generate_strategy_builder_returns_validation_error_for_over_limit_date_edit(
    client,
    db_session,
):
    plan = db_session.query(Plan).filter(Plan.code == "TEST_PRO").one()
    plan.max_backtest_years = 3
    db_session.commit()
    db_session.refresh(plan)
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change start date to 2020-01-01",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["config"] is None
    assert "plan limit" in body["message"]


def test_generate_strategy_builder_returns_validation_error_for_confirmation_without_current_draft(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "VALIDATION_ERROR"
    assert "existing draft" in body["message"]
    assert "confirmation" in body["message"]


def test_generate_strategy_builder_draft_uses_symbol_history_aware_default_window_for_long_history(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2010, 1, 1), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a mean reversion strategy for QQQ"},
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "CREATE_DRAFT"
    assert config["tradable_symbol"] == "QQQ"
    assert config["end_date"] == "2026-04-17"
    assert config["start_date"] == "2018-01-02"


def test_generate_strategy_builder_draft_shortens_default_window_for_newer_symbol_history(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT"},
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["tradable_symbol"] == "IBIT"
    assert config["start_date"] == "2024-01-11"
    assert config["end_date"] == "2026-04-17"


def test_generate_strategy_builder_draft_preserves_explicit_dates_even_with_symbol_history(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT from 2025-01-01 to 2026-03-01"},
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["start_date"] == "2025-01-01"
    assert config["end_date"] == "2026-03-01"


def test_generate_strategy_builder_draft_falls_back_when_metadata_is_missing(
    client,
    monkeypatch,
):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a mean reversion strategy for QQQ"},
    )

    assert response.status_code == 200
    config = response.json()["config"]
    settings = get_settings()

    assert config["tradable_symbol"] == "QQQ"
    assert config["start_date"] == settings.supported_data_start.isoformat()
    assert config["end_date"] == settings.supported_data_end.isoformat()


def test_generate_strategy_builder_draft_returns_assumptions_in_response(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "CREATE_DRAFT"
    assert any(
        "Used available history for IBIT starting on 2024-01-11." in item
        for item in body["assumptions"]
    )
    assert any(
        "Used the default backtest range 2024-01-11 to 2026-04-17." in item
        for item in body["assumptions"]
    )


def test_generate_strategy_builder_summary_mentions_available_history_when_metadata_shortens_window(
    client,
    monkeypatch,
):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_parsers,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2024, 1, 11), date(2026, 4, 17)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for IBIT"},
    )

    assert response.status_code == 200
    body = response.json()

    assert "using available history" in body["summary"]
    assert "from 2024-01-11 to 2026-04-17" in body["summary"]
    assert "from 2024-01-11 to 2026-04-17. Enter when" in body["summary"]


def test_generate_strategy_builder_summary_mentions_default_platform_range_when_metadata_is_missing(
    client,
    monkeypatch,
):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a mean reversion strategy for QQQ"},
    )

    assert response.status_code == 200
    body = response.json()

    assert "using the default platform range" in body["summary"]


def test_generate_strategy_builder_returns_friendlier_unsupported_symbol_message(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for AAPL"},
    )

    assert response.status_code == 400
    assert "not supported yet" in response.json()["detail"]
    assert "ETF-first" in response.json()["detail"]


def test_generate_strategy_builder_returns_friendlier_plan_limit_message(
    client,
    db_session,
):
    plan = db_session.query(Plan).filter(Plan.code == "TEST_PRO").one()
    plan.max_backtest_years = 5
    db_session.commit()
    db_session.refresh(plan)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for QQQ from 2018-01-02 to 2026-04-14",
        },
    )

    assert response.status_code == 400
    assert "current plan limit" in response.json()["detail"]
    assert "shorten the range" in response.json()["detail"]


def test_generate_strategy_builder_returns_validation_error_for_unsupported_edit_type(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add bollinger bands confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert "not supported yet" in body["message"]
    assert "You can ask me to change RSI thresholds" in body["message"]
    assert "rotation lookback, top N, fallback, or risk filter" in body["message"]
    assert "benchmark" in body["message"]


def test_generate_strategy_builder_returns_structured_supported_symbols_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What ETFs are available?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_SYMBOLS"
    assert "QQQ" in body["answer_data"]["supported_symbols"]
    assert "SPY" in body["message"]


def test_generate_strategy_builder_returns_symbol_data_coverage_answer(client, monkeypatch):
    class StubHistory:
        def __init__(self, symbol, first_date, last_date):
            self.symbol = symbol
            self.first_available_date = first_date
            self.last_available_date = last_date

    monkeypatch.setattr(
        builder_response,
        "get_etf_history_range",
        lambda symbol: StubHistory(symbol, date(2010, 1, 4), date(2026, 4, 24)),
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What date range is available for QQQ?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "DATA_COVERAGE"
    assert body["answer_data"]["supported_symbols"] == ["QQQ"]
    assert body["answer_data"]["supported_data_start"] == "2010-01-04"
    assert body["answer_data"]["supported_data_end"] == "2026-04-24"
    assert body["answer_data"]["max_backtest_years"] is not None
    assert "QQQ coverage is available" in body["message"]


def test_generate_strategy_builder_returns_data_coverage_fallback_when_metadata_missing(
    client,
    monkeypatch,
):
    monkeypatch.setattr(builder_response, "get_etf_history_range", lambda symbol: None)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What date range is available for QQQ?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "DATA_COVERAGE"
    assert body["answer_data"]["supported_symbols"] == ["QQQ"]
    assert body["answer_data"]["supported_data_start"] is None
    assert "could not find coverage metadata for QQQ" in body["message"]


def test_generate_strategy_builder_returns_general_data_coverage_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What date range is supported?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "DATA_COVERAGE"
    assert body["answer_data"]["supported_data_start"] is not None
    assert body["answer_data"]["supported_data_end"] is not None
    assert body["answer_data"]["max_backtest_years"] is not None


def test_generate_strategy_builder_returns_unsupported_stock_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Can I test NVDA?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_SYMBOLS"
    assert "NVDA is not currently available" in body["message"]
    assert "ETF strategy research" in body["message"]
    assert "QQQ" in body["message"]
    assert "SPY" in body["message"]


def test_generate_strategy_builder_returns_benchmark_symbol_guidance(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Can I use SPY as benchmark?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_SYMBOLS"
    assert "SPY" in body["message"]
    assert "benchmark" in body["message"]


def test_generate_strategy_builder_returns_structured_plan_limits_answer(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "What are my plan limits?"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["answer_data"]["answer_type"] == "PLAN_LIMITS"
    assert body["answer_data"]["max_backtest_years"] is not None


@pytest.mark.parametrize(
    "prompt",
    [
        "What strategies can I build?",
        "What indicators are supported?",
        "What can I ask you to do?",
    ],
)
def test_generate_strategy_builder_returns_structured_supported_strategy_types_answer(client, prompt):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "ANSWER"
    assert body["config"] is None
    assert body["answer_data"]["answer_type"] == "SUPPORTED_STRATEGY_TYPES"
    assert body["message"] == (
        "You can currently build ETF strategies using RSI mean reversion, SMA / moving-average crossover, "
        "SMA trend-state rules, MACD, KD / stochastic, relative strength, VIX and rates filters, "
        "yield-curve filters, realized volatility, seasonality, stop loss, take profit, cooldown, "
        "benchmark comparison, and core-overlay allocation."
    )
    assert "RSI mean reversion" in body["message"]
    assert "SMA / moving-average crossover" in body["message"]
    assert "SMA trend-state rules" in body["message"]
    assert "MACD" in body["message"]
    assert "KD" in body["message"]
    assert "relative strength" in body["message"]
    assert "VIX and rates filters" in body["message"]
    assert "yield-curve filters" in body["message"]
    assert "seasonality" in body["message"]
    assert "stop loss" in body["message"]
    assert "take profit" in body["message"]
    assert "cooldown" in body["message"]
    assert "benchmark comparison" in body["message"]
    assert "core-overlay allocation" in body["message"]

    internal_terms = [
        "nested",
        "direct removal",
        "NOT wrapper",
        "sequence",
        "composite replacement",
        "parser",
        "window inner",
        "group operator",
        "confirmation filter",
    ]
    for term in internal_terms:
        assert term.lower() not in body["message"].lower()


def test_generate_strategy_builder_returns_structured_validation_data_for_unsupported_symbol(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a strategy for AAPL"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "not supported yet" in detail


def test_generate_strategy_builder_returns_structured_validation_error_for_unsupported_edit_type(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add bollinger bands confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["validation_data"]["validation_type"] == "UNSUPPORTED_EDIT"
    assert body["validation_data"]["suggested_action"] is not None
    assert "MACD" in body["validation_data"]["suggested_action"]
    assert "KD" in body["validation_data"]["suggested_action"]
    assert "seasonality" in body["validation_data"]["suggested_action"]
    assert "relative strength" in body["validation_data"]["suggested_action"]
    assert "entry size" in body["validation_data"]["suggested_action"]


def test_generate_strategy_builder_returns_guidance_data_for_no_change_response(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "tell me what this draft can do",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "ANSWER"
    assert body["guidance_data"]["guidance_type"] == "NO_CHANGE"
    assert len(body["guidance_data"]["suggested_actions"]) > 0
    assert "Change tradable symbol" in body["guidance_data"]["suggested_actions"]
    assert "Change entry size" in body["guidance_data"]["suggested_actions"]
    assert "Adjust max position" in body["guidance_data"]["suggested_actions"]
    assert "Change transaction cost" in body["guidance_data"]["suggested_actions"]
    assert "Adjust RSI thresholds" in body["guidance_data"]["suggested_actions"]
    assert "Edit nested RSI settings" in body["guidance_data"]["suggested_actions"]
    assert "Switch moving-average rules" in body["guidance_data"]["suggested_actions"]
    assert "Edit nested moving-average windows" in body["guidance_data"]["suggested_actions"]
    assert "Switch to MACD" in body["guidance_data"]["suggested_actions"]
    assert "Switch to KD / stochastic" in body["guidance_data"]["suggested_actions"]
    assert "Switch to seasonality by month" in body["guidance_data"]["suggested_actions"]
    assert "Edit seasonality months" in body["guidance_data"]["suggested_actions"]
    assert "Add / remove seasonality months" in body["guidance_data"]["suggested_actions"]
    assert "Switch to relative strength" in body["guidance_data"]["suggested_actions"]
    assert "Switch to SMA above" in body["guidance_data"]["suggested_actions"]
    assert "Edit nested relative strength settings" in body["guidance_data"]["suggested_actions"]
    assert "Add MACD confirmation" in body["guidance_data"]["suggested_actions"]
    assert "Add KD / stochastic confirmation" in body["guidance_data"]["suggested_actions"]
    assert "Add relative strength confirmation" in body["guidance_data"]["suggested_actions"]
    assert "Remove confirmation filters" in body["guidance_data"]["suggested_actions"]
    assert "Change window bars / mode" in body["guidance_data"]["suggested_actions"]
    assert "Change sequence bars / steps" in body["guidance_data"]["suggested_actions"]
    assert "Change group operator" in body["guidance_data"]["suggested_actions"]
    assert "Change group conditions" in body["guidance_data"]["suggested_actions"]
    assert "Change window inner rule" in body["guidance_data"]["suggested_actions"]
    assert "Adjust partial take profit" in body["guidance_data"]["suggested_actions"]
    assert "Adjust position management" in body["guidance_data"]["suggested_actions"]
    assert "Change scale-in fraction" in body["guidance_data"]["suggested_actions"]
    assert "Change max scale-in entries" in body["guidance_data"]["suggested_actions"]
    assert "Change bars between adds" in body["guidance_data"]["suggested_actions"]
    assert "Remove scale-in policy" in body["guidance_data"]["suggested_actions"]
    assert "Enable / disable core allocation" in body["guidance_data"]["suggested_actions"]
    assert "Change NOT inner rule" in body["guidance_data"]["suggested_actions"]
    assert "Remove NOT wrapper" in body["guidance_data"]["suggested_actions"]
    assert "Remove group conditions" in body["guidance_data"]["suggested_actions"]
    assert "Remove window wrapper" in body["guidance_data"]["suggested_actions"]
    assert "Remove sequence steps" in body["guidance_data"]["suggested_actions"]


def test_generate_strategy_builder_returns_guidance_data_for_unsupported_edit_target(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add bollinger bands confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "QQQ",
                    "reference_symbols": [],
                    "start_date": "2021-04-14",
                    "end_date": "2026-04-14",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["guidance_data"]["guidance_type"] == "UNSUPPORTED_EDIT_TARGET"
    assert len(body["guidance_data"]["suggested_actions"]) > 0


def test_generate_strategy_builder_updates_only_exit_sma_slow_window(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit rule slow window to 20",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_above",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_below",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 5
    assert config["entry_rule"]["slow_window"] == 10

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 5
    assert config["exit_rule"]["slow_window"] == 20


def test_generate_strategy_builder_does_not_replace_exit_rule_with_fallback_rsi_on_partial_exit_edit(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit rule slow window to 20",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_above",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_below",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["config"]

    assert config["exit_rule"]["type"] != "rsi_above"
    assert config["exit_rule"]["symbol"] == "SPY"


def test_generate_strategy_builder_updates_only_entry_sma_fast_window_with_sma_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry SMA fast window to 8",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_above",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_below",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 8
    assert config["entry_rule"]["slow_window"] == 10

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 5
    assert config["exit_rule"]["slow_window"] == 10


def test_generate_strategy_builder_updates_only_entry_sma_slow_window_with_sma_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry SMA slow window to 21",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_above",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_below",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 5
    assert config["entry_rule"]["slow_window"] == 21

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 5
    assert config["exit_rule"]["slow_window"] == 10


def test_generate_strategy_builder_updates_only_exit_sma_fast_window_with_sma_phrase(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit SMA fast window to 7",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "spy-sma-cross-above-to-sma-cross-below",
                    "tradable_symbol": "SPY",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2021-04-17",
                    "end_date": "2026-04-17",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_above",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "sma_cross_below",
                        "symbol": "SPY",
                        "fast_window": 5,
                        "slow_window": 10,
                    },
                    "risk": {"cooldown_bars": 0},
                    "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "UPDATE_DRAFT"

    config = body["config"]
    assert config["entry_rule"]["type"] == "sma_cross_above"
    assert config["entry_rule"]["fast_window"] == 5
    assert config["entry_rule"]["slow_window"] == 10

    assert config["exit_rule"]["type"] == "sma_cross_below"
    assert config["exit_rule"]["fast_window"] == 7
    assert config["exit_rule"]["slow_window"] == 10


def test_generate_strategy_builder_draft_defaults_position_management_to_none(client):
    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create an SMA crossover strategy for SPY"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["response_type"] == "CREATE_DRAFT"
    config = body["config"]

    assert config["tradable_symbol"] == "SPY"
    assert config["allocation"]["entry_value"] == 1.0
    assert config["allocation"]["max_position_pct"] == 1.0
    assert config["core_overlay"]["enabled"] is False

    # Critical alignment check:
    # missing position_management should stay absent/null in generated drafts
    assert "position_management" not in config or config["position_management"] is None


def test_generate_strategy_builder_draft_updates_top_level_seasonality_months(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change seasonality months to March and April",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-seasonality-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "month_in",
                        "month_values": [1, 2, 3],
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "month_in",
                            "month_values": [1, 2, 3],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["month_values"] == [3, 4]
    assert config["exit_rule"]["rule"]["month_values"] == [3, 4]


def test_generate_strategy_builder_draft_adds_month_to_nested_seasonality_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add March to seasonality months",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-seasonality-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "month_in",
                                "month_values": [1, 2],
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["rules"][1]["month_values"] == [1, 2, 3]


def test_generate_strategy_builder_draft_removes_month_from_seasonality_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove February from seasonality months",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-seasonality-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "month_in",
                        "month_values": [1, 2, 3],
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "atomic",
                            "type": "month_in",
                            "month_values": [1, 2, 3],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["month_values"] == [1, 3]
    assert config["exit_rule"]["rule"]["month_values"] == [1, 3]


def test_generate_strategy_builder_draft_updates_nested_entry_rsi_settings(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry rsi threshold to 25 and change entry rsi lookback to 10",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-entry-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_rsi = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_rsi["type"] == "rsi_below"
    assert nested_rsi["threshold"] == 25
    assert nested_rsi["lookback"] == 10
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_updates_nested_exit_rsi_settings(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit rsi threshold to 65 and change exit rsi lookback to 21",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-exit-rsi-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 70,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_rsi = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_rsi["type"] == "rsi_above"
    assert nested_rsi["threshold"] == 65
    assert nested_rsi["lookback"] == 21


def test_generate_strategy_builder_draft_updates_nested_entry_moving_average_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry fast window to 10 and change entry slow window to 40",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-entry-sma-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "sma_cross_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_sma = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_sma["type"] == "sma_cross_above"
    assert nested_sma["fast_window"] == 10
    assert nested_sma["slow_window"] == 40
    assert config["entry_rule"]["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_updates_nested_exit_moving_average_windows(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit fast window to 15 and change exit slow window to 60",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-exit-sma-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_sma = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_sma["type"] == "sma_above"
    assert nested_sma["fast_window"] == 15
    assert nested_sma["slow_window"] == 60


def test_generate_strategy_builder_draft_removes_nested_macd_confirmation_from_entry_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-macd-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bullish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["rule"]["kind"] == "atomic"
    assert config["entry_rule"]["rule"]["type"] == "rsi_below"


def test_generate_strategy_builder_draft_removes_nested_macd_confirmation_from_exit_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-macd-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_above",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 70,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bearish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"


def test_generate_strategy_builder_draft_updates_entry_group_condition_to_window_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change first condition of entry group to any RSI below 25 within 5 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-group-window-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "atomic",
                                "type": "rsi_below",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 30,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_rule = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_rule["kind"] == "window"
    assert updated_rule["window_bars"] == 5
    assert updated_rule["mode"] == "ANY"
    assert updated_rule["rule"]["kind"] == "atomic"
    assert updated_rule["rule"]["type"] == "rsi_below"
    assert updated_rule["rule"]["threshold"] == 25


def test_generate_strategy_builder_draft_updates_exit_sequence_step_to_group_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second step of exit sequence to RSI above 70 and MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-sequence-group-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "sequence",
                        "window_bars": 4,
                        "steps": [
                            {
                                "kind": "atomic",
                                "type": "rsi_above",
                                "symbol": "QQQ",
                                "lookback": 14,
                                "threshold": 70,
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bearish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_step = config["exit_rule"]["steps"][1]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_step["kind"] == "group"
    assert updated_step["operator"] == "AND"
    assert updated_step["rules"][0]["type"] == "rsi_above"
    assert updated_step["rules"][0]["threshold"] == 70
    assert updated_step["rules"][1]["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_updates_nested_exit_not_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit not inner rule to RSI above 65",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_rule = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "not"
    assert nested_rule["kind"] == "atomic"
    assert nested_rule["type"] == "rsi_above"
    assert nested_rule["threshold"] == 65


def test_generate_strategy_builder_draft_removes_nested_exit_not_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove exit not wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-not-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "not",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert response.status_code == 200
    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "sma_above"
    assert config["exit_rule"]["rule"]["fast_window"] == 20
    assert config["exit_rule"]["rule"]["slow_window"] == 50


def test_generate_strategy_builder_draft_updates_nested_entry_group_operator(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry group operator to OR",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-group-operator-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bullish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert config["entry_rule"]["rule"]["kind"] == "group"
    assert config["entry_rule"]["rule"]["operator"] == "OR"


def test_generate_strategy_builder_draft_updates_nested_exit_group_condition(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change first condition of exit group to all RSI above 75 within 4 bars",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-group-condition-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "group",
                            "operator": "AND",
                            "rules": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_above",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 70,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bearish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_rule = config["exit_rule"]["rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_rule["kind"] == "window"
    assert updated_rule["window_bars"] == 4
    assert updated_rule["mode"] == "ALL"
    assert updated_rule["rule"]["kind"] == "atomic"
    assert updated_rule["rule"]["type"] == "rsi_above"
    assert updated_rule["rule"]["threshold"] == 75


def test_generate_strategy_builder_draft_updates_nested_entry_window_bars_and_mode(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change entry window to 6 bars and change entry window mode to all",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-window-edit-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "window",
                                "window_bars": 3,
                                "mode": "ANY",
                                "rule": {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_window = config["entry_rule"]["rules"][0]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert nested_window["kind"] == "window"
    assert nested_window["window_bars"] == 6
    assert nested_window["mode"] == "ALL"


def test_generate_strategy_builder_draft_updates_nested_exit_window_inner_rule(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change exit window inner rule to MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-window-inner-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "not",
                        "rule": {
                            "kind": "window",
                            "window_bars": 3,
                            "mode": "ANY",
                            "rule": {
                                "kind": "atomic",
                                "type": "sma_above",
                                "symbol": "QQQ",
                                "fast_window": 20,
                                "slow_window": 50,
                            },
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    nested_window_rule = config["exit_rule"]["rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "not"
    assert config["exit_rule"]["rule"]["kind"] == "window"
    assert nested_window_rule["kind"] == "atomic"
    assert nested_window_rule["type"] == "macd_bearish_cross"


def test_generate_strategy_builder_draft_updates_nested_entry_sequence_step(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "change second step of entry sequence to RSI below 20 and MACD",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-sequence-step-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "sequence",
                                "window_bars": 4,
                                "steps": [
                                    {
                                        "kind": "atomic",
                                        "type": "rsi_below",
                                        "symbol": "QQQ",
                                        "lookback": 14,
                                        "threshold": 30,
                                    },
                                    {
                                        "kind": "atomic",
                                        "type": "sma_cross_above",
                                        "symbol": "QQQ",
                                        "fast_window": 20,
                                        "slow_window": 50,
                                    },
                                ],
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    updated_step = config["entry_rule"]["rules"][0]["steps"][1]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert updated_step["kind"] == "group"
    assert updated_step["operator"] == "AND"
    assert updated_step["rules"][0]["type"] == "rsi_below"
    assert updated_step["rules"][0]["threshold"] == 20
    assert updated_step["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_removes_nested_exit_sequence_step(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove second step of exit sequence",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-sequence-remove-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "sequence",
                            "window_bars": 4,
                            "steps": [
                                {
                                    "kind": "atomic",
                                    "type": "rsi_above",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 70,
                                },
                                {
                                    "kind": "atomic",
                                    "type": "macd_bearish_cross",
                                    "symbol": "QQQ",
                                },
                            ],
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert config["exit_rule"]["rule"]["kind"] == "atomic"
    assert config["exit_rule"]["rule"]["type"] == "rsi_above"


def test_generate_strategy_builder_draft_removes_nested_entry_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "remove entry window wrapper",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-nested-window-remove-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "group",
                        "operator": "AND",
                        "rules": [
                            {
                                "kind": "window",
                                "window_bars": 3,
                                "mode": "ANY",
                                "rule": {
                                    "kind": "atomic",
                                    "type": "rsi_below",
                                    "symbol": "QQQ",
                                    "lookback": 14,
                                    "threshold": 30,
                                },
                            },
                            {
                                "kind": "atomic",
                                "type": "macd_bullish_cross",
                                "symbol": "QQQ",
                            },
                        ],
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "group"
    assert config["entry_rule"]["rules"][0]["kind"] == "atomic"
    assert config["entry_rule"]["rules"][0]["type"] == "rsi_below"


def test_generate_strategy_builder_draft_adds_macd_confirmation_inside_entry_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-confirmation-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_below",
                            "symbol": "QQQ",
                            "lookback": 14,
                            "threshold": 30,
                        },
                    },
                    "exit_rule": {
                        "kind": "atomic",
                        "type": "rsi_above",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 70,
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    inner_rule = config["entry_rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["entry_rule"]["kind"] == "window"
    assert inner_rule["kind"] == "group"
    assert inner_rule["operator"] == "AND"
    assert inner_rule["rules"][0]["type"] == "rsi_below"
    assert inner_rule["rules"][1]["type"] == "macd_bullish_cross"


def test_generate_strategy_builder_draft_adds_macd_confirmation_inside_exit_window_wrapper(client):
    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "add MACD confirmation",
            "context": {
                "mode": "NEW_VERSION",
                "current_config": {
                    "schema_version": "2.0",
                    "name": "qqq-window-confirmation-test",
                    "tradable_symbol": "QQQ",
                    "benchmark_symbol": "SPY",
                    "reference_symbols": [],
                    "start_date": "2019-01-02",
                    "end_date": "2024-12-31",
                    "initial_capital": 100000,
                    "transaction_cost_bps": 5,
                    "allocation": {
                        "entry_mode": "percent_of_equity",
                        "entry_value": 1.0,
                        "max_position_pct": 1.0,
                    },
                    "entry_rule": {
                        "kind": "atomic",
                        "type": "rsi_below",
                        "symbol": "QQQ",
                        "lookback": 14,
                        "threshold": 30,
                    },
                    "exit_rule": {
                        "kind": "window",
                        "window_bars": 3,
                        "mode": "ANY",
                        "rule": {
                            "kind": "atomic",
                            "type": "rsi_above",
                            "symbol": "QQQ",
                            "lookback": 14,
                            "threshold": 70,
                        },
                    },
                    "risk": {
                        "cooldown_bars": 0,
                    },
                    "core_overlay": {
                        "enabled": False,
                        "core_allocation_pct": 0.0,
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    config = body["config"]

    inner_rule = config["exit_rule"]["rule"]

    assert body["response_type"] == "UPDATE_DRAFT"
    assert config["exit_rule"]["kind"] == "window"
    assert inner_rule["kind"] == "group"
    assert inner_rule["operator"] == "AND"
    assert inner_rule["rules"][0]["type"] == "rsi_above"
    assert inner_rule["rules"][1]["type"] == "macd_bearish_cross"
