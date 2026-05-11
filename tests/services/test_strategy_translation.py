from __future__ import annotations

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderContext,
    StrategyBuilderGenerateRequest,
)
from market_simulator.services.strategy_translation import (
    LlmTranslationProvider,
    build_strategy_translation_request,
    translate_strategy_builder_request,
)


def _valid_single_etf_config(**overrides):
    config = {
        "schema_version": "2.0",
        "name": "QQQ RSI Strategy",
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
    config.update(overrides)
    return config


def test_default_translation_provider_uses_deterministic_builder(monkeypatch):
    req = StrategyBuilderGenerateRequest(
        prompt="Create a QQQ RSI strategy that buys below 30 and sells above 70."
    )
    monkeypatch.setattr(
        "market_simulator.services.strategy_builder_parsers.get_etf_history_range",
        lambda symbol: None,
    )

    result = translate_strategy_builder_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    body = result.response_payload()

    assert body["translation_provider"] == "deterministic"
    assert body["translation_mode"] == "deterministic"
    assert body["llm_enabled"] is False
    assert body["response_type"] == "CREATE_DRAFT"
    assert body["config"]["tradable_symbol"] == "QQQ"


def test_disabled_llm_provider_returns_guidance_without_external_call():
    req = StrategyBuilderGenerateRequest(prompt="Use an LLM to make a strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = LlmTranslationProvider(enabled=False)

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert result["llm_enabled"] is False
    assert "LLM translation is not enabled" in result["message"]


def test_placeholder_llm_contract_must_validate_before_returning():
    req = StrategyBuilderGenerateRequest(prompt="Create a QQQ RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = LlmTranslationProvider(
        enabled=True,
        contract_output={
            "action": "create_config",
            "full_config": _valid_single_etf_config(),
            "summary": "Translated a QQQ RSI Strategy V2 draft.",
        },
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "CREATE_DRAFT"
    assert result["translation_provider"] == "llm"
    assert result["llm_enabled"] is True
    assert result["config"]["schema_version"] == "2.0"


def test_invalid_llm_contract_is_rejected_with_useful_guidance():
    invalid_config = _valid_single_etf_config()
    invalid_config.pop("exit_rule")
    req = StrategyBuilderGenerateRequest(prompt="Create a QQQ RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = LlmTranslationProvider(
        enabled=True,
        contract_output={
            "action": "create_config",
            "full_config": invalid_config,
            "summary": "Translated a QQQ RSI Strategy V2 draft.",
        },
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert "I could not build a valid strategy draft" in result["message"]
    assert result["validation_data"]["validation_type"] == "GENERAL"


def test_llm_contract_with_unsupported_symbol_is_rejected():
    req = StrategyBuilderGenerateRequest(prompt="Create a TSLA RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = LlmTranslationProvider(
        enabled=True,
        contract_output={
            "action": "create_config",
            "full_config": _valid_single_etf_config(
                name="TSLA RSI Strategy",
                tradable_symbol="TSLA",
                benchmark_symbol="TSLA",
            ),
            "summary": "Translated a TSLA RSI Strategy V2 draft.",
        },
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert "TSLA is not supported yet" in result["message"]
    assert result["validation_data"]["validation_type"] == "UNSUPPORTED_SYMBOL"


def test_llm_patch_uses_current_config_and_returns_update_draft():
    current_config = _valid_single_etf_config()
    req = StrategyBuilderGenerateRequest(
        prompt="Change max position to 50%.",
        context=StrategyBuilderContext(current_config=current_config),
    )
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = LlmTranslationProvider(
        enabled=True,
        contract_output={
            "action": "edit_config",
            "config_patch": {"allocation": {"max_position_pct": 0.5}},
            "summary": "Updated the QQQ RSI Strategy V2 draft.",
        },
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "UPDATE_DRAFT"
    assert result["config"]["allocation"]["max_position_pct"] == 0.5
