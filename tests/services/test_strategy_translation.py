from __future__ import annotations

import json

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderContext,
    StrategyBuilderGenerateRequest,
)
from market_simulator import settings as settings_module
from market_simulator.settings import Settings
from market_simulator.services.strategy_translation import (
    LlmTranslationProvider,
    OpenAIStrategyTranslationProvider,
    build_strategy_translation_request,
    select_strategy_translation_provider,
    translate_strategy_builder_request,
)


class _FakeOpenAIResponses:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(self.payload),
                        }
                    ]
                }
            ]
        }


class _FakeOpenAIClient:
    def __init__(self, payload=None, error: Exception | None = None):
        self.responses = _FakeOpenAIResponses(payload=payload, error=error)


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


def test_openai_provider_is_not_selected_unless_configured(monkeypatch):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            strategy_builder_provider="deterministic",
            openai_api_key="test-key",
        ),
    )

    provider = select_strategy_translation_provider(requested_mode="openai")

    assert provider.name == "deterministic"


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


def test_openai_provider_missing_api_key_returns_safe_guidance(monkeypatch):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            strategy_builder_provider="openai",
            openai_api_key=None,
        ),
    )
    req = StrategyBuilderGenerateRequest(prompt="Create a QQQ RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(api_key=None)

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert result["translation_provider"] == "openai"
    assert result["translation_mode"] == "llm"
    assert result["llm_enabled"] is False
    assert "OPENAI_API_KEY is not set" in result["message"]


def test_openai_mocked_structured_response_is_validated_and_returned():
    req = StrategyBuilderGenerateRequest(prompt="Create a QQQ RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    fake_client = _FakeOpenAIClient(
        payload={
            "action": "create_config",
            "full_config": _valid_single_etf_config(),
            "summary": "Translated a QQQ RSI Strategy V2 draft.",
            "changes": ["Created QQQ RSI entry and exit rules."],
        },
    )
    provider = OpenAIStrategyTranslationProvider(client=fake_client)

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "CREATE_DRAFT"
    assert result["translation_provider"] == "openai"
    assert result["translation_mode"] == "llm"
    assert result["llm_enabled"] is True
    assert result["config"]["tradable_symbol"] == "QQQ"
    assert result["changes"] == ["Created QQQ RSI entry and exit rules."]
    call = fake_client.responses.calls[0]
    assert call["model"]
    assert call["text"]["format"]["type"] == "json_schema"


def test_openai_mocked_invalid_config_is_rejected_with_guidance():
    invalid_config = _valid_single_etf_config()
    invalid_config.pop("exit_rule")
    req = StrategyBuilderGenerateRequest(prompt="Create a QQQ RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(
            payload={
                "action": "create_config",
                "full_config": invalid_config,
                "summary": "Translated a QQQ RSI Strategy V2 draft.",
            },
        )
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert result["translation_provider"] == "openai"
    assert "I could not build a valid strategy draft" in result["message"]
    assert result["validation_data"]["validation_type"] == "GENERAL"


def test_openai_mocked_unsupported_symbol_is_rejected():
    req = StrategyBuilderGenerateRequest(prompt="Create a TSLA RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(
            payload={
                "action": "create_config",
                "full_config": _valid_single_etf_config(
                    name="TSLA RSI Strategy",
                    tradable_symbol="TSLA",
                    benchmark_symbol="TSLA",
                ),
                "summary": "Translated a TSLA RSI Strategy V2 draft.",
            },
        )
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert "TSLA is not supported yet" in result["message"]
    assert result["validation_data"]["validation_type"] == "UNSUPPORTED_SYMBOL"


def test_openai_provider_error_returns_safe_guidance_without_raw_error():
    req = StrategyBuilderGenerateRequest(prompt="Create a QQQ RSI strategy.")
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(error=TimeoutError("secret upstream stack trace"))
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert result["translation_provider"] == "openai"
    assert "temporarily unavailable" in result["message"]
    assert "secret upstream stack trace" not in result["message"]


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
