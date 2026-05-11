from __future__ import annotations

import json
import logging

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


def _valid_rotation_block(**overrides):
    block = {
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
        "risk_filter": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 200,
        },
        "fallback": {
            "type": "asset",
            "symbol": "TLT",
        },
    }
    block.update(overrides)
    return block


def _valid_rotation_config(**overrides):
    config = {
        "schema_version": "2.0",
        "name": "QQQ SPY XLK TLT Rotation",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": ["SPY", "XLK", "TLT"],
        "start_date": "2021-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": None,
        "entry_rule": None,
        "exit_rule": None,
        "risk": {
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
        "position_management": None,
        "rotation": _valid_rotation_block(),
    }
    config.update(overrides)
    return config


def test_default_translation_provider_uses_deterministic_builder(monkeypatch):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            strategy_builder_provider="deterministic",
        ),
    )
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


def test_deterministic_translation_emits_safe_timing_without_changing_payload(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            strategy_builder_provider="deterministic",
            strategy_builder_log_translation_timing=True,
        ),
    )
    req = StrategyBuilderGenerateRequest(
        prompt="Create a QQQ RSI strategy that buys below 30 and sells above 70."
    )
    monkeypatch.setattr(
        "market_simulator.services.strategy_builder_parsers.get_etf_history_range",
        lambda symbol: None,
    )

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        result = translate_strategy_builder_request(
            req,
            entitlements={"plan_code": "TEST"},
            max_backtest_years=10,
        )

    body = result.response_payload()
    log_text = caplog.text
    assert body["translation_provider"] == "deterministic"
    assert "diagnostics" not in body
    assert "strategy_builder.deterministic_provider" in log_text
    assert "strategy_builder.translation" in log_text
    assert "provider=deterministic" in log_text
    assert "prompt_chars=" in log_text
    assert req.prompt not in log_text
    assert any(record.name == "uvicorn.error" for record in caplog.records)


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


def test_openai_mocked_structured_response_emits_size_and_latency_logs(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            strategy_builder_log_translation_timing=True,
        ),
    )
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
        },
    )
    provider = OpenAIStrategyTranslationProvider(
        client=fake_client,
        model="gpt-test",
    )

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        result = provider.translate(translation_request).response_payload()

    log_text = caplog.text
    assert result["response_type"] == "CREATE_DRAFT"
    assert "diagnostics" not in result
    assert "strategy_builder.openai_request" in log_text
    assert "strategy_builder.openai_response" in log_text
    assert "strategy_builder.validation" in log_text
    assert "strategy_builder.openai_provider" in log_text
    assert "model=gpt-test" in log_text
    assert "api_ms=" in log_text
    assert "extraction_ms=" in log_text
    assert "contract_ms=" in log_text
    assert "guardrail_ms=" in log_text
    assert "strategy_v2_ms=" in log_text
    assert "prompt_chars=" in log_text
    assert "system_chars=" in log_text
    assert "context_chars=" in log_text
    assert "schema_chars=" in log_text
    assert "response_chars=" in log_text
    assert req.prompt not in log_text
    assert "Translated a QQQ RSI Strategy V2 draft." not in log_text
    assert any(record.name == "uvicorn.error" for record in caplog.records)


def test_openai_latency_logs_redact_api_key_and_avoid_raw_payloads(
    monkeypatch,
    caplog,
):
    secret_key = "test-secret-latency-key"
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            openai_api_key=secret_key,
            strategy_builder_log_translation_timing=True,
        ),
    )
    prompt = f"Create a QQQ strategy. Do not log {secret_key}."
    req = StrategyBuilderGenerateRequest(prompt=prompt)
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    fake_client = _FakeOpenAIClient(
        payload={
            "action": "create_config",
            "full_config": _valid_single_etf_config(name=secret_key),
            "summary": f"Translated with {secret_key}.",
        },
    )
    provider = OpenAIStrategyTranslationProvider(
        client=fake_client,
        api_key=secret_key,
        model="gpt-test",
    )

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        result = provider.translate(translation_request).response_payload()

    log_text = caplog.text
    assert result["response_type"] == "CREATE_DRAFT"
    assert secret_key not in log_text
    assert prompt not in log_text
    assert f"Translated with {secret_key}." not in log_text
    assert "strategy_builder.openai_response" in log_text
    assert "response_chars=" in log_text


def test_openai_mocked_rotation_block_only_is_repaired_into_valid_config():
    req = StrategyBuilderGenerateRequest(
        prompt=(
            "Create a monthly rotation between QQQ, SPY, XLK, and TLT using "
            "3-month momentum. Add a SPY 200-day SMA risk filter and fallback to TLT."
        )
    )
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(
            payload={
                "action": "create_config",
                "full_config": _valid_rotation_block(),
                "summary": "Translated a cross-asset rotation Strategy V2 draft.",
            },
        )
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "CREATE_DRAFT"
    config = result["config"]
    assert config["schema_version"] == "2.0"
    assert config["tradable_symbol"] == "QQQ"
    assert config["benchmark_symbol"] == "SPY"
    assert config["reference_symbols"] == ["SPY", "XLK", "TLT"]
    assert config["initial_capital"] == 100000
    assert config["transaction_cost_bps"] == 5
    assert config["risk"]["cooldown_bars"] == 0
    assert config["core_overlay"] == {
        "enabled": False,
        "core_allocation_pct": 0.0,
    }
    assert config["rotation"]["enabled"] is True


def test_openai_mocked_rotation_missing_tradable_symbol_defaults_to_first_universe():
    incomplete_config = _valid_rotation_config(reference_symbols=[])
    incomplete_config.pop("tradable_symbol")
    req = StrategyBuilderGenerateRequest(
        prompt=(
            "Create a monthly rotation between QQQ, SPY, XLK, and TLT using "
            "3-month momentum. Add a SPY 200-day SMA risk filter and fallback to TLT."
        )
    )
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(
            payload={
                "action": "create_config",
                "full_config": incomplete_config,
                "summary": "Translated a cross-asset rotation Strategy V2 draft.",
            },
        )
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "CREATE_DRAFT"
    config = result["config"]
    assert config["tradable_symbol"] == "QQQ"
    assert config["reference_symbols"] == ["SPY", "XLK", "TLT"]
    assert config["rotation"]["risk_filter"] == {
        "kind": "atomic",
        "type": "sma_above",
        "symbol": "SPY",
        "fast_window": 1,
        "slow_window": 200,
    }
    assert config["rotation"]["fallback"] == {
        "type": "asset",
        "symbol": "TLT",
    }


def test_openai_mocked_rotation_reference_symbols_are_derived_from_dependencies():
    incomplete_config = _valid_rotation_config(
        tradable_symbol="QQQ",
        reference_symbols=[],
    )
    req = StrategyBuilderGenerateRequest(
        prompt="Create a monthly rotation between QQQ, SPY, XLK, and TLT."
    )
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(
            payload={
                "action": "create_config",
                "full_config": incomplete_config,
                "summary": "Translated a rotation Strategy V2 draft.",
            },
        )
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "CREATE_DRAFT"
    assert result["config"]["reference_symbols"] == ["SPY", "XLK", "TLT"]


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


def test_openai_mocked_rotation_unsupported_symbol_still_fails():
    req = StrategyBuilderGenerateRequest(
        prompt="Create a monthly rotation between TSLA and QQQ using 3-month momentum."
    )
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(
            payload={
                "action": "create_config",
                "full_config": _valid_rotation_block(universe=["TSLA", "QQQ"]),
                "summary": "Translated a rotation Strategy V2 draft.",
            },
        )
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert "TSLA is not supported yet" in result["message"]
    assert result["validation_data"]["validation_type"] == "UNSUPPORTED_SYMBOL"


def test_openai_mocked_rotation_invalid_ranking_type_still_fails():
    req = StrategyBuilderGenerateRequest(
        prompt="Create a monthly rotation between QQQ, SPY, XLK, and TLT ranked by Sharpe."
    )
    translation_request = build_strategy_translation_request(
        req,
        entitlements={"plan_code": "TEST"},
        max_backtest_years=10,
    )
    provider = OpenAIStrategyTranslationProvider(
        client=_FakeOpenAIClient(
            payload={
                "action": "create_config",
                "full_config": _valid_rotation_block(
                    ranking={
                        "type": "sharpe",
                        "lookback": 63,
                        "descending": True,
                    },
                ),
                "summary": "Translated a rotation Strategy V2 draft.",
            },
        )
    )

    result = provider.translate(translation_request).response_payload()

    assert result["response_type"] == "VALIDATION_ERROR"
    assert "rotation.ranking.type" in result["message"]


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
