from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import timedelta
import json
import logging
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderAnswerType,
    StrategyBuilderGenerateRequest,
    StrategyBuilderGuidanceType,
    StrategyBuilderResponseType,
    StrategyBuilderValidationType,
)
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.services.draft_validation import collect_draft_config_warnings
from market_simulator.services.strategy_builder_guardrails import (
    validate_strategy_builder_request,
)
from market_simulator.services.strategy_builder_response import (
    _build_guidance_data,
    _build_response,
    build_validation_data,
)
from market_simulator.settings import get_settings


DETERMINISTIC_PROVIDER = "deterministic"
HYBRID_PROVIDER = "hybrid"
LLM_PROVIDER = "llm"
OPENAI_PROVIDER = "openai"

logger = logging.getLogger(__name__)
TIMING_LOGGER_NAME = "uvicorn.error"


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _safe_log_value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, float):
        return f"{value:.2f}"
    text = str(value).replace("\n", "\\n").replace(" ", "_")
    return _redact_sensitive_values(text)


def _redact_sensitive_values(value: str) -> str:
    settings = get_settings()
    api_key = settings.openai_api_key
    redacted = value
    if api_key:
        redacted = redacted.replace(api_key, "<redacted>")
    redacted = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", redacted)
    return redacted


def log_strategy_builder_timing(event: str, **fields: Any) -> None:
    if not get_settings().strategy_builder_log_translation_timing:
        return
    safe_fields = " ".join(
        f"{key}={_safe_log_value(value)}" for key, value in fields.items()
    )
    logging.getLogger(TIMING_LOGGER_NAME).info("%s %s", event, safe_fields)


def log_strategy_builder_openai_usage(**fields: Any) -> None:
    safe_fields = " ".join(
        f"{key}={_safe_log_value(value)}" for key, value in fields.items()
    )
    logging.getLogger(TIMING_LOGGER_NAME).info(
        "strategy_builder.openai_usage %s",
        safe_fields,
    )


class StrategyTranslationProviderUnavailable(RuntimeError):
    """Raised when an explicitly configured provider cannot be used safely."""


class StrategyTranslationProviderError(RuntimeError):
    """Raised when a provider call fails and should be reported safely."""


@dataclass(frozen=True)
class StrategyTranslationRequest:
    prompt: str
    current_config: dict[str, Any] | None
    context_mode: str | None
    max_backtest_years: int
    user_entitlements: dict[str, Any]
    supported_symbols: tuple[str, ...]
    supported_reference_symbols: tuple[str, ...]
    raw_request: StrategyBuilderGenerateRequest
    openai_allowed: bool = True
    openai_block_reason: str | None = None
    openai_limit: int | None = None
    openai_used_today: int | None = None


@dataclass(frozen=True)
class StrategyTranslationResult:
    response: dict[str, Any]
    translation_provider: str
    translation_mode: str
    llm_enabled: bool
    validation_errors: list[str]
    diagnostics: dict[str, Any] = dataclass_field(default_factory=dict)

    def response_payload(self) -> dict[str, Any]:
        payload = dict(self.response)
        payload.setdefault("translation_provider", self.translation_provider)
        payload.setdefault("translation_mode", self.translation_mode)
        payload.setdefault("llm_enabled", self.llm_enabled)
        payload.setdefault("translation_fallback_used", False)
        payload.setdefault(
            "deterministic_attempted",
            self.translation_provider == DETERMINISTIC_PROVIDER,
        )
        payload.setdefault(
            "openai_attempted",
            self.translation_provider == OPENAI_PROVIDER,
        )
        return payload


class LlmStructuredTranslationOutput(BaseModel):
    """Structured JSON contract expected from a future LLM translation provider.

    A provider may suggest only declarative Strategy V2 JSON. It must not return
    executable code, provider-specific tool calls, or simulation instructions.
    The backend applies schema validation, symbol validation, entitlement checks,
    and config normalization after this contract is parsed.
    """

    action: Literal["create_config", "edit_config", "guidance"]
    full_config: dict[str, Any] | None = None
    config_patch: dict[str, Any] | None = None
    explanation: str | None = None
    summary: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config_payload(self) -> "LlmStructuredTranslationOutput":
        if self.action in {"create_config", "edit_config"}:
            if self.full_config is None and self.config_patch is None:
                raise ValueError("LLM config actions must include full_config or config_patch")
        if self.action == "create_config" and self.config_patch is not None and self.full_config is None:
            raise ValueError("create_config requires full_config unless a complete config is provided")
        return self


class StrategyTranslationProvider(ABC):
    name: str
    mode: str
    llm_enabled: bool

    @abstractmethod
    def translate(self, request: StrategyTranslationRequest) -> StrategyTranslationResult:
        raise NotImplementedError


class DeterministicTranslationProvider(StrategyTranslationProvider):
    name = DETERMINISTIC_PROVIDER
    mode = DETERMINISTIC_PROVIDER
    llm_enabled = False

    def translate(self, request: StrategyTranslationRequest) -> StrategyTranslationResult:
        start = time.perf_counter()
        from market_simulator.services.strategy_builder_service import (
            generate_strategy_builder_response,
        )

        response = generate_strategy_builder_response(
            request.raw_request,
            max_backtest_years=request.max_backtest_years,
        )
        deterministic_ms = _elapsed_ms(start)
        log_strategy_builder_timing(
            "strategy_builder.deterministic_provider",
            provider=self.name,
            mode=self.mode,
            total_ms=deterministic_ms,
            prompt_chars=len(request.prompt),
        )
        return StrategyTranslationResult(
            response=response,
            translation_provider=self.name,
            translation_mode=self.mode,
            llm_enabled=self.llm_enabled,
            validation_errors=[],
            diagnostics={"deterministic_ms": deterministic_ms},
        )


class LlmTranslationProvider(StrategyTranslationProvider):
    """Disabled placeholder for a future provider-backed translator.

    This class intentionally has no API client, no credentials, and no network
    behavior. Tests may pass a prepared contract payload to exercise the backend
    validation path a real provider would use later.
    """

    name = LLM_PROVIDER
    mode = LLM_PROVIDER

    def __init__(
        self,
        *,
        enabled: bool = False,
        contract_output: LlmStructuredTranslationOutput | dict[str, Any] | None = None,
    ) -> None:
        self.llm_enabled = enabled
        self._contract_output = contract_output

    def translate(self, request: StrategyTranslationRequest) -> StrategyTranslationResult:
        if not self.llm_enabled or self._contract_output is None:
            message = (
                "LLM translation is not enabled for this environment. "
                "The deterministic Strategy V2 builder remains available."
            )
            response = _build_response(
                response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
                message=message,
                validation_data=build_validation_data(
                    message=message,
                    max_backtest_years=request.max_backtest_years,
                ),
                guidance_data=_build_guidance_data(
                    guidance_type=StrategyBuilderGuidanceType.GENERAL_GUIDANCE,
                ),
            )
            return StrategyTranslationResult(
                response=response,
                translation_provider=self.name,
                translation_mode=self.mode,
                llm_enabled=False,
                validation_errors=[message],
            )

        try:
            contract = (
                self._contract_output
                if isinstance(self._contract_output, LlmStructuredTranslationOutput)
                else LlmStructuredTranslationOutput.model_validate(self._contract_output)
            )
            contract.provider_metadata.setdefault("provider", self.name)
            response = build_strategy_builder_response_from_llm_contract(
                contract,
                request=request,
            )
            return StrategyTranslationResult(
                response=response,
                translation_provider=self.name,
                translation_mode=self.mode,
                llm_enabled=True,
                validation_errors=[],
            )
        except (ValidationError, ValueError) as exc:
            message = _format_translation_error(exc)
            response = _build_response(
                response_type=StrategyBuilderResponseType.VALIDATION_ERROR,
                message=message,
                validation_data=build_validation_data(
                    message=message,
                    max_backtest_years=request.max_backtest_years,
                ),
                guidance_data=_build_guidance_data(
                    guidance_type=StrategyBuilderGuidanceType.GENERAL_GUIDANCE,
                ),
            )
            return StrategyTranslationResult(
                response=response,
                translation_provider=self.name,
                translation_mode=self.mode,
                llm_enabled=True,
                validation_errors=[message],
            )


class OpenAIStrategyTranslationProvider(StrategyTranslationProvider):
    """OpenAI-backed Strategy Builder translator, disabled unless configured.

    The provider returns only the shared structured contract. The shared
    validation and normalization pipeline decides whether a config can be
    returned to the frontend.
    """

    name = OPENAI_PROVIDER
    mode = LLM_PROVIDER

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.model = model or settings.openai_model
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.openai_timeout_seconds
        )
        self.max_retries = (
            max_retries if max_retries is not None else settings.openai_max_retries
        )
        self._client = client
        self.llm_enabled = bool(self.api_key or self._client is not None)
        self._last_request_diagnostics: dict[str, Any] = {}

    def translate(self, request: StrategyTranslationRequest) -> StrategyTranslationResult:
        provider_start = time.perf_counter()
        validation_diagnostics: dict[str, Any] = {}
        if not self.llm_enabled:
            message = (
                "OpenAI Strategy Builder translation is configured, but OPENAI_API_KEY "
                "is not set. The deterministic Strategy V2 builder remains available."
            )
            provider_ms = _elapsed_ms(provider_start)
            log_strategy_builder_timing(
                "strategy_builder.openai_provider",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                total_ms=provider_ms,
                status="missing_api_key",
                prompt_chars=len(request.prompt),
            )
            return _provider_guidance_result(
                message=message,
                provider=self.name,
                mode=self.mode,
                llm_enabled=False,
                max_backtest_years=request.max_backtest_years,
                diagnostics={
                    "openai_provider_ms": provider_ms,
                    "openai_usage_status": "provider_error",
                    "model": self.model,
                    "provider": self.name,
                    "mode": self.mode,
                    "prompt_chars": len(request.prompt),
                },
            )

        try:
            self._last_request_diagnostics = {}
            contract = self._request_contract(request)
            request_diagnostics = dict(self._last_request_diagnostics)
            validation_diagnostics["contract_ms"] = request_diagnostics.get("contract_ms")
            contract.provider_metadata.setdefault("provider", self.name)
        except StrategyTranslationProviderUnavailable as exc:
            message = str(exc)
            provider_ms = _elapsed_ms(provider_start)
            log_strategy_builder_timing(
                "strategy_builder.openai_provider",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                total_ms=provider_ms,
                status="unavailable",
                prompt_chars=len(request.prompt),
            )
            return _provider_guidance_result(
                message=message,
                provider=self.name,
                mode=self.mode,
                llm_enabled=False,
                max_backtest_years=request.max_backtest_years,
                diagnostics={
                    "openai_provider_ms": provider_ms,
                    "openai_usage_status": "provider_error",
                    **self._last_request_diagnostics,
                },
            )
        except (ValidationError, ValueError) as exc:
            message = _format_translation_error(exc)
            provider_ms = _elapsed_ms(provider_start)
            log_strategy_builder_timing(
                "strategy_builder.openai_provider",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                total_ms=provider_ms,
                status="invalid_contract",
                prompt_chars=len(request.prompt),
            )
            return _provider_guidance_result(
                message=message,
                provider=self.name,
                mode=self.mode,
                llm_enabled=True,
                max_backtest_years=request.max_backtest_years,
                diagnostics={
                    "openai_provider_ms": provider_ms,
                    "openai_usage_status": "validation_error",
                    **self._last_request_diagnostics,
                },
            )
        except Exception:
            message = (
                "OpenAI Strategy Builder translation is temporarily unavailable. "
                "The deterministic Strategy V2 builder remains available."
            )
            provider_ms = _elapsed_ms(provider_start)
            log_strategy_builder_timing(
                "strategy_builder.openai_provider",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                total_ms=provider_ms,
                status="error",
                prompt_chars=len(request.prompt),
            )
            return _provider_guidance_result(
                message=message,
                provider=self.name,
                mode=self.mode,
                llm_enabled=True,
                max_backtest_years=request.max_backtest_years,
                diagnostics={
                    "openai_provider_ms": provider_ms,
                    "openai_usage_status": self._last_request_diagnostics.get(
                        "openai_usage_status",
                        "provider_error",
                    ),
                    **self._last_request_diagnostics,
                },
            )

        try:
            response = build_strategy_builder_response_from_llm_contract(
                contract,
                request=request,
                diagnostics=validation_diagnostics,
            )
            provider_ms = _elapsed_ms(provider_start)
            log_strategy_builder_timing(
                "strategy_builder.openai_provider",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                total_ms=provider_ms,
                status="ok",
                prompt_chars=len(request.prompt),
            )
            return StrategyTranslationResult(
                response=response,
                translation_provider=self.name,
                translation_mode=self.mode,
                llm_enabled=True,
                validation_errors=[],
                diagnostics={
                    "openai_provider_ms": provider_ms,
                    "openai_usage_status": "success",
                    **request_diagnostics,
                    **validation_diagnostics,
                },
            )
        except (ValidationError, ValueError) as exc:
            message = _format_translation_error(exc)
            provider_ms = _elapsed_ms(provider_start)
            log_strategy_builder_timing(
                "strategy_builder.openai_provider",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                total_ms=provider_ms,
                status="invalid_strategy",
                prompt_chars=len(request.prompt),
            )
            return _provider_guidance_result(
                message=message,
                provider=self.name,
                mode=self.mode,
                llm_enabled=True,
                max_backtest_years=request.max_backtest_years,
                diagnostics={
                    "openai_provider_ms": provider_ms,
                    **request_diagnostics,
                    **validation_diagnostics,
                    "openai_usage_status": "validation_error",
                },
            )

    def _request_contract(
        self,
        request: StrategyTranslationRequest,
    ) -> LlmStructuredTranslationOutput:
        self._last_request_diagnostics = {}
        client = self._client or self._build_client()
        responses = getattr(client, "responses", None)
        create_response = getattr(responses, "create", None)
        if create_response is None:
            raise StrategyTranslationProviderUnavailable(
                "The installed OpenAI SDK does not support the Responses API. "
                "Install or upgrade the optional OpenAI SDK to enable this provider."
            )

        instructions = _openai_translation_instructions()
        context_json = json.dumps(
            _openai_translation_context(request),
            sort_keys=True,
        )
        schema = LlmStructuredTranslationOutput.model_json_schema()
        schema_json = json.dumps(schema, sort_keys=True)
        output_text = ""
        api_ms: float | None = None
        extraction_ms: float | None = None
        contract_ms: float | None = None
        status = "ok"
        usage_metadata: dict[str, Any] = {}

        try:
            request_start = time.perf_counter()
            response = create_response(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": instructions,
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": context_json,
                            }
                        ],
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "strategy_translation_output",
                        "schema": schema,
                        "strict": False,
                    }
                },
            )
            api_ms = _elapsed_ms(request_start)
            usage_metadata = _extract_openai_usage_metadata(response)
            extraction_start = time.perf_counter()
            output_text = _extract_response_text(response)
            extraction_ms = _elapsed_ms(extraction_start)
            if not output_text:
                status = "empty_response"
                raise StrategyTranslationProviderError(
                    "OpenAI response did not include JSON output."
                )
            contract_start = time.perf_counter()
            try:
                contract = LlmStructuredTranslationOutput.model_validate_json(output_text)
                contract_ms = _elapsed_ms(contract_start)
                return contract
            except ValidationError as exc:
                status = "invalid_contract"
                contract_ms = _elapsed_ms(contract_start)
                _log_provider_validation_failure(
                    provider=self.name,
                    exc=exc,
                    provider_output=output_text,
                )
                raise
        except Exception as exc:
            if status == "ok":
                status = _openai_error_status(exc)
                if api_ms is None:
                    api_ms = _elapsed_ms(request_start)
            raise
        finally:
            estimated_cost_usd = _estimate_openai_cost_usd(usage_metadata)
            self._last_request_diagnostics = {
                "api_ms": api_ms,
                "extraction_ms": extraction_ms,
                "contract_ms": contract_ms,
                "prompt_chars": len(request.prompt),
                "system_chars": len(instructions),
                "context_chars": len(context_json),
                "schema_chars": len(schema_json),
                "response_chars": len(output_text),
                "model": self.model,
                "provider": self.name,
                "mode": self.mode,
                "openai_usage_status": _openai_usage_status_from_request_status(status),
                "input_tokens": usage_metadata.get("input_tokens"),
                "output_tokens": usage_metadata.get("output_tokens"),
                "total_tokens": usage_metadata.get("total_tokens"),
                "estimated_cost_usd": estimated_cost_usd,
            }
            log_strategy_builder_timing(
                "strategy_builder.openai_request",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                status=status,
                api_ms=api_ms,
                prompt_chars=len(request.prompt),
                system_chars=len(instructions),
                context_chars=len(context_json),
                schema_chars=len(schema_json),
                input_tokens=usage_metadata.get("input_tokens"),
                output_tokens=usage_metadata.get("output_tokens"),
                total_tokens=usage_metadata.get("total_tokens"),
            )
            log_strategy_builder_timing(
                "strategy_builder.openai_response",
                provider=self.name,
                mode=self.mode,
                model=self.model,
                status=status,
                extraction_ms=extraction_ms,
                contract_ms=contract_ms,
                response_chars=len(output_text),
            )

    def _build_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise StrategyTranslationProviderUnavailable(
                "OpenAI Strategy Builder translation is configured, but the optional "
                "OpenAI SDK is not installed. Install it only in environments that "
                "enable STRATEGY_BUILDER_PROVIDER=openai."
            ) from exc

        return OpenAI(
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )


class HybridStrategyTranslationProvider(StrategyTranslationProvider):
    name = HYBRID_PROVIDER
    mode = HYBRID_PROVIDER
    llm_enabled = False

    def __init__(
        self,
        *,
        primary_provider: StrategyTranslationProvider | None = None,
        fallback_provider: StrategyTranslationProvider | None = None,
    ) -> None:
        self.primary_provider = primary_provider or DeterministicTranslationProvider()
        self.fallback_provider = fallback_provider or OpenAIStrategyTranslationProvider()
        self.llm_enabled = bool(getattr(self.fallback_provider, "llm_enabled", False))

    def translate(self, request: StrategyTranslationRequest) -> StrategyTranslationResult:
        hybrid_start = time.perf_counter()
        deterministic_result = self.primary_provider.translate(request)
        deterministic_success, deterministic_error = _is_successful_deterministic_result(
            deterministic_result,
            request=request,
        )
        deterministic_ms = deterministic_result.diagnostics.get("deterministic_ms")

        if deterministic_success:
            total_ms = _elapsed_ms(hybrid_start)
            diagnostics = {
                **deterministic_result.diagnostics,
                "hybrid_total_ms": total_ms,
                "deterministic_success": True,
                "openai_attempted": False,
            }
            log_strategy_builder_timing(
                "strategy_builder.hybrid_provider",
                provider=self.name,
                mode=self.mode,
                deterministic_ms=deterministic_ms,
                deterministic_success=True,
                openai_fallback_called=False,
                openai_provider_ms=None,
                total_ms=total_ms,
                prompt_chars=len(request.prompt),
            )
            return _with_hybrid_metadata(
                deterministic_result,
                fallback_used=False,
                openai_attempted=False,
                diagnostics=diagnostics,
            )

        if _is_non_fallbackable_deterministic_result(deterministic_result):
            total_ms = _elapsed_ms(hybrid_start)
            diagnostics = {
                **deterministic_result.diagnostics,
                "hybrid_total_ms": total_ms,
                "deterministic_success": False,
                "deterministic_error": deterministic_error,
                "openai_attempted": False,
                "fallback_blocked_by_policy": True,
            }
            log_strategy_builder_timing(
                "strategy_builder.hybrid_provider",
                provider=self.name,
                mode=self.mode,
                deterministic_ms=deterministic_ms,
                deterministic_success=False,
                openai_fallback_called=False,
                openai_provider_ms=None,
                total_ms=total_ms,
                prompt_chars=len(request.prompt),
            )
            return _with_hybrid_metadata(
                deterministic_result,
                fallback_used=False,
                openai_attempted=False,
                diagnostics=diagnostics,
            )

        if not getattr(self.fallback_provider, "llm_enabled", False):
            total_ms = _elapsed_ms(hybrid_start)
            deterministic_response = _with_ai_unavailable_note(
                deterministic_result.response,
            )
            diagnostics = {
                **deterministic_result.diagnostics,
                "hybrid_total_ms": total_ms,
                "deterministic_success": False,
                "deterministic_error": deterministic_error,
                "openai_attempted": False,
            }
            log_strategy_builder_timing(
                "strategy_builder.hybrid_provider",
                provider=self.name,
                mode=self.mode,
                deterministic_ms=deterministic_ms,
                deterministic_success=False,
                openai_fallback_called=False,
                openai_provider_ms=None,
                total_ms=total_ms,
                prompt_chars=len(request.prompt),
            )
            return _with_hybrid_metadata(
                StrategyTranslationResult(
                    response=deterministic_response,
                    translation_provider=deterministic_result.translation_provider,
                    translation_mode=deterministic_result.translation_mode,
                    llm_enabled=False,
                    validation_errors=deterministic_result.validation_errors,
                    diagnostics=diagnostics,
                ),
                fallback_used=False,
                openai_attempted=False,
                diagnostics=diagnostics,
            )

        if not request.openai_allowed:
            total_ms = _elapsed_ms(hybrid_start)
            deterministic_response = _with_ai_fallback_blocked_note(
                deterministic_result.response,
                request=request,
            )
            diagnostics = {
                **deterministic_result.diagnostics,
                "hybrid_total_ms": total_ms,
                "deterministic_success": False,
                "deterministic_error": deterministic_error,
                "openai_attempted": False,
                "fallback_blocked_by_limit": True,
                "openai_block_reason": request.openai_block_reason,
                "openai_limit": request.openai_limit,
                "openai_used_today": request.openai_used_today,
            }
            log_strategy_builder_timing(
                "strategy_builder.hybrid_provider",
                provider=self.name,
                mode=self.mode,
                deterministic_ms=deterministic_ms,
                deterministic_success=False,
                openai_fallback_called=False,
                openai_provider_ms=None,
                total_ms=total_ms,
                prompt_chars=len(request.prompt),
                fallback_blocked_by_limit=True,
            )
            log_strategy_builder_openai_usage(
                provider=OPENAI_PROVIDER,
                mode="hybrid_fallback",
                status="limit_blocked",
                fallback_used=False,
                prompt_chars=len(request.prompt),
                openai_limit=request.openai_limit,
                openai_used_today=request.openai_used_today,
                reason=request.openai_block_reason,
            )
            return _with_hybrid_metadata(
                StrategyTranslationResult(
                    response=deterministic_response,
                    translation_provider=deterministic_result.translation_provider,
                    translation_mode=deterministic_result.translation_mode,
                    llm_enabled=False,
                    validation_errors=deterministic_result.validation_errors,
                    diagnostics=diagnostics,
                ),
                fallback_used=False,
                openai_attempted=False,
                diagnostics=diagnostics,
            )

        fallback_result = self.fallback_provider.translate(request)
        total_ms = _elapsed_ms(hybrid_start)
        diagnostics = {
            **deterministic_result.diagnostics,
            **fallback_result.diagnostics,
            "hybrid_total_ms": total_ms,
            "deterministic_success": False,
            "deterministic_error": deterministic_error,
            "openai_attempted": True,
        }
        log_strategy_builder_timing(
            "strategy_builder.hybrid_provider",
            provider=self.name,
            mode=self.mode,
            deterministic_ms=deterministic_ms,
            deterministic_success=False,
            openai_fallback_called=True,
            openai_provider_ms=diagnostics.get("openai_provider_ms"),
            total_ms=total_ms,
            prompt_chars=len(request.prompt),
        )
        return _with_hybrid_metadata(
            fallback_result,
            fallback_used=True,
            openai_attempted=True,
            diagnostics=diagnostics,
        )


def build_strategy_translation_request(
    req: StrategyBuilderGenerateRequest,
    *,
    entitlements: Any,
    max_backtest_years: int,
    openai_allowed: bool = True,
    openai_block_reason: str | None = None,
    openai_limit: int | None = None,
    openai_used_today: int | None = None,
) -> StrategyTranslationRequest:
    settings = get_settings()
    current_config = req.context.current_config if req.context else None
    return StrategyTranslationRequest(
        prompt=req.prompt,
        current_config=current_config if isinstance(current_config, dict) else None,
        context_mode=req.context.mode if req.context else None,
        max_backtest_years=max_backtest_years,
        user_entitlements=_entitlements_snapshot(entitlements),
        supported_symbols=settings.supported_etf_symbols,
        supported_reference_symbols=settings.supported_reference_series_symbols,
        raw_request=req,
        openai_allowed=openai_allowed,
        openai_block_reason=openai_block_reason,
        openai_limit=openai_limit,
        openai_used_today=openai_used_today,
    )


def select_strategy_translation_provider(
    *,
    requested_mode: str | None = None,
) -> StrategyTranslationProvider:
    settings = get_settings()
    configured_provider = settings.strategy_builder_provider.strip().lower()
    explicit_mode = (requested_mode or "").strip().lower()
    requested_llm = explicit_mode in {"llm", "ai", "natural_language_llm"}

    if configured_provider == OPENAI_PROVIDER:
        return OpenAIStrategyTranslationProvider()

    if configured_provider == HYBRID_PROVIDER:
        return HybridStrategyTranslationProvider()

    if configured_provider == LLM_PROVIDER and settings.strategy_builder_llm_enabled:
        return LlmTranslationProvider(enabled=True)

    if requested_llm and settings.strategy_builder_llm_enabled:
        return LlmTranslationProvider(enabled=True)

    return DeterministicTranslationProvider()


def translate_strategy_builder_request(
    req: StrategyBuilderGenerateRequest,
    *,
    entitlements: Any,
    max_backtest_years: int,
    provider: StrategyTranslationProvider | None = None,
    openai_allowed: bool = True,
    openai_block_reason: str | None = None,
    openai_limit: int | None = None,
    openai_used_today: int | None = None,
) -> StrategyTranslationResult:
    total_start = time.perf_counter()
    translation_request = build_strategy_translation_request(
        req,
        entitlements=entitlements,
        max_backtest_years=max_backtest_years,
        openai_allowed=openai_allowed,
        openai_block_reason=openai_block_reason,
        openai_limit=openai_limit,
        openai_used_today=openai_used_today,
    )
    selected_provider = provider or select_strategy_translation_provider(
        requested_mode=translation_request.context_mode,
    )
    result = selected_provider.translate(translation_request)
    total_ms = _elapsed_ms(total_start)
    diagnostics = dict(result.diagnostics)
    diagnostics["total_ms"] = total_ms
    log_strategy_builder_timing(
        "strategy_builder.translation",
        provider=result.translation_provider,
        mode=result.translation_mode,
        model=getattr(selected_provider, "model", None),
        total_ms=total_ms,
        deterministic_ms=diagnostics.get("deterministic_ms"),
        openai_provider_ms=diagnostics.get("openai_provider_ms"),
        prompt_chars=len(req.prompt),
    )
    return _with_provider_metadata(
        StrategyTranslationResult(
            response=result.response,
            translation_provider=result.translation_provider,
            translation_mode=result.translation_mode,
            llm_enabled=result.llm_enabled,
            validation_errors=result.validation_errors,
            diagnostics=diagnostics,
        )
    )


def build_strategy_builder_response_from_llm_contract(
    contract: LlmStructuredTranslationOutput,
    *,
    request: StrategyTranslationRequest,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if contract.action == "guidance":
        message = _guidance_message(contract)
        return _build_response(
            response_type=StrategyBuilderResponseType.ANSWER,
            message=message,
            warnings=contract.warnings,
            assumptions=contract.assumptions,
            guidance_data=_build_guidance_data(
                guidance_type=StrategyBuilderGuidanceType.GENERAL_GUIDANCE,
            ),
        )

    candidate_config = _candidate_config_from_contract(contract, request=request)
    try:
        normalized_config = normalize_translated_strategy_config(
            candidate_config,
            prompt=request.prompt,
            max_backtest_years=request.max_backtest_years,
            diagnostics=diagnostics,
        )
    except (ValidationError, ValueError) as exc:
        provider = _contract_provider_name(contract)
        if diagnostics is not None:
            log_strategy_builder_timing(
                "strategy_builder.validation",
                provider=provider,
                contract_ms=diagnostics.get("contract_ms"),
                guardrail_ms=diagnostics.get("guardrail_ms"),
                strategy_v2_ms=diagnostics.get("strategy_v2_ms"),
                normalization_ms=diagnostics.get("normalization_ms"),
                status="invalid_strategy",
            )
        _log_provider_validation_failure(
            provider=provider,
            exc=exc,
            provider_output=contract.model_dump(mode="json", exclude_none=True),
        )
        raise

    if diagnostics is not None:
        log_strategy_builder_timing(
            "strategy_builder.validation",
            provider=_contract_provider_name(contract),
            contract_ms=diagnostics.get("contract_ms"),
            guardrail_ms=diagnostics.get("guardrail_ms"),
            strategy_v2_ms=diagnostics.get("strategy_v2_ms"),
            normalization_ms=diagnostics.get("normalization_ms"),
        )

    summary = _summary_from_contract(contract, normalized_config)
    warnings = list(contract.warnings)
    for warning in collect_draft_config_warnings(normalized_config):
        if warning not in warnings:
            warnings.append(warning)

    if contract.unsupported_features:
        warnings.append(
            "Unsupported features were not included: "
            + ", ".join(contract.unsupported_features)
            + "."
        )

    if _contains_performance_promise(summary) or _contains_performance_promise(
        contract.explanation or ""
    ):
        raise ValueError(
            "LLM translation output included performance promises. "
            "Generated strategy text must describe rules without promising returns."
        )

    return _build_response(
        response_type=(
            StrategyBuilderResponseType.UPDATE_DRAFT
            if request.current_config
            else StrategyBuilderResponseType.CREATE_DRAFT
        ),
        message=summary,
        config=normalized_config,
        summary=summary,
        warnings=warnings,
        assumptions=contract.assumptions,
        changes=contract.changes,
    )


def normalize_translated_strategy_config(
    config: dict[str, Any],
    *,
    prompt: str,
    max_backtest_years: int,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalization_start = time.perf_counter()
    guardrail_ms: float | None = None
    strategy_v2_ms: float | None = None
    try:
        config = _repair_rotation_config_defaults(
            config,
            max_backtest_years=max_backtest_years,
        )
        guardrail_start = time.perf_counter()
        validate_strategy_builder_request(
            prompt=prompt,
            config=config,
            max_backtest_years=max_backtest_years,
        )
        guardrail_ms = _elapsed_ms(guardrail_start)
        strategy_v2_start = time.perf_counter()
        strategy = StrategyV2.model_validate(config)
        normalized = strategy.model_dump(mode="json", exclude_none=True)
        strategy_v2_ms = _elapsed_ms(strategy_v2_start)
        return normalized
    finally:
        if diagnostics is not None:
            diagnostics.update(
                {
                    "guardrail_ms": guardrail_ms,
                    "strategy_v2_ms": strategy_v2_ms,
                    "normalization_ms": _elapsed_ms(normalization_start),
                }
            )


def _repair_rotation_config_defaults(
    config: dict[str, Any],
    *,
    max_backtest_years: int,
) -> dict[str, Any]:
    if not isinstance(config, dict):
        return config

    repaired = deepcopy(config)
    if _looks_like_standalone_rotation_block(repaired):
        repaired = {"rotation": repaired}

    rotation = repaired.get("rotation")
    if not isinstance(rotation, dict) or rotation.get("enabled") is not True:
        return repaired

    universe = _normalized_symbol_list(rotation.get("universe"))
    if not universe:
        return repaired

    rotation["universe"] = universe
    settings = get_settings()

    repaired.setdefault("schema_version", "2.0")
    if not _non_empty_string(repaired.get("tradable_symbol")):
        repaired["tradable_symbol"] = universe[0]
    else:
        repaired["tradable_symbol"] = str(repaired["tradable_symbol"]).upper()

    if not _non_empty_string(repaired.get("benchmark_symbol")):
        repaired["benchmark_symbol"] = (
            "SPY" if "SPY" in settings.supported_etf_symbols else universe[0]
        )
    else:
        repaired["benchmark_symbol"] = str(repaired["benchmark_symbol"]).upper()

    if not _non_empty_string(repaired.get("name")):
        repaired["name"] = _derive_rotation_strategy_name(rotation)

    start_date, end_date = _platform_default_date_range(
        max_backtest_years=max_backtest_years,
    )
    repaired.setdefault("start_date", start_date)
    repaired.setdefault("end_date", end_date)
    repaired.setdefault("initial_capital", 100000)
    repaired.setdefault("transaction_cost_bps", 5)

    if not isinstance(repaired.get("risk"), dict):
        repaired["risk"] = {"cooldown_bars": 0}
    else:
        repaired["risk"].setdefault("cooldown_bars", 0)

    if not isinstance(repaired.get("core_overlay"), dict):
        repaired["core_overlay"] = {"enabled": False, "core_allocation_pct": 0.0}
    else:
        repaired["core_overlay"].setdefault("enabled", False)
        repaired["core_overlay"].setdefault("core_allocation_pct", 0.0)

    repaired["reference_symbols"] = _derive_rotation_reference_symbols(repaired)
    return repaired


def _looks_like_standalone_rotation_block(config: dict[str, Any]) -> bool:
    return (
        config.get("enabled") is True
        and "rotation" not in config
        and any(key in config for key in ("universe", "ranking", "rebalance", "selection"))
    )


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized_symbol_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    symbols: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        symbol = item.strip().upper()
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _platform_default_date_range(*, max_backtest_years: int) -> tuple[str, str]:
    settings = get_settings()
    end_date = settings.supported_data_end
    approx_days = int(max_backtest_years * 365.25)
    candidate_start = end_date - timedelta(days=approx_days)
    start_date = max(settings.supported_data_start, candidate_start)
    return start_date.isoformat(), end_date.isoformat()


def _derive_rotation_strategy_name(rotation: dict[str, Any]) -> str:
    universe = _normalized_symbol_list(rotation.get("universe"))
    ranking = rotation.get("ranking") if isinstance(rotation.get("ranking"), dict) else {}
    selection = (
        rotation.get("selection")
        if isinstance(rotation.get("selection"), dict)
        else {}
    )
    lookback = ranking.get("lookback")
    top_n = selection.get("top_n")

    universe_label = "/".join(universe[:4]) if universe else "ETF"
    lookback_label = f"{lookback}-day " if isinstance(lookback, int) else ""
    top_label = f"Top {top_n} " if isinstance(top_n, int) else ""
    return f"{universe_label} {lookback_label}{top_label}Rotation".strip()


def _derive_rotation_reference_symbols(config: dict[str, Any]) -> list[str]:
    rotation = config.get("rotation") if isinstance(config.get("rotation"), dict) else {}
    tradable_symbol = (
        str(config.get("tradable_symbol")).upper()
        if _non_empty_string(config.get("tradable_symbol"))
        else None
    )

    symbols: list[str] = []
    existing = config.get("reference_symbols")
    if isinstance(existing, list):
        for symbol in existing:
            _append_reference_symbol(symbols, symbol, tradable_symbol)

    for symbol in rotation.get("universe") or []:
        _append_reference_symbol(symbols, symbol, tradable_symbol)

    _append_reference_symbol(symbols, config.get("benchmark_symbol"), tradable_symbol)
    for symbol in _collect_rule_symbols(rotation.get("risk_filter")):
        _append_reference_symbol(symbols, symbol, tradable_symbol)

    fallback = rotation.get("fallback") if isinstance(rotation.get("fallback"), dict) else {}
    if fallback.get("type") == "asset":
        _append_reference_symbol(symbols, fallback.get("symbol"), tradable_symbol)

    return symbols


def _append_reference_symbol(
    symbols: list[str],
    value: Any,
    tradable_symbol: str | None,
) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    symbol = value.strip().upper()
    if symbol == tradable_symbol or symbol in symbols:
        return
    symbols.append(symbol)


def _collect_rule_symbols(rule: Any) -> list[str]:
    if not isinstance(rule, dict):
        return []

    kind = rule.get("kind")
    if kind == "atomic":
        symbols: list[str] = []
        for field_name in ("symbol", "reference_symbol"):
            value = rule.get(field_name)
            if isinstance(value, str):
                symbols.append(value.upper())
        return symbols
    if kind == "not":
        return _collect_rule_symbols(rule.get("rule"))
    if kind in {"group", "sequence"}:
        child_key = "rules" if kind == "group" else "steps"
        symbols: list[str] = []
        for child in rule.get(child_key) or []:
            symbols.extend(_collect_rule_symbols(child))
        return symbols
    if kind == "window":
        return _collect_rule_symbols(rule.get("rule"))
    return []


def _candidate_config_from_contract(
    contract: LlmStructuredTranslationOutput,
    *,
    request: StrategyTranslationRequest,
) -> dict[str, Any]:
    if contract.full_config is not None:
        return deepcopy(contract.full_config)

    if contract.config_patch is None:
        raise ValueError("LLM translation did not include a Strategy V2 config.")

    if request.current_config is None:
        raise ValueError("LLM config_patch requires an existing current_config.")

    return _deep_merge_dicts(request.current_config, contract.config_patch)


def _deep_merge_dicts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _guidance_message(contract: LlmStructuredTranslationOutput) -> str:
    if contract.explanation:
        return contract.explanation
    if contract.unsupported_features:
        return (
            "That request includes unsupported features: "
            + ", ".join(contract.unsupported_features)
            + "."
        )
    return "I can translate supported ETF strategy ideas into validated Strategy V2 drafts."


def _summary_from_contract(
    contract: LlmStructuredTranslationOutput,
    config: dict[str, Any],
) -> str:
    summary = contract.summary or contract.explanation
    if summary:
        return summary
    name = str(config.get("name") or "Strategy V2 draft")
    return f"Translated a validated Strategy V2 draft for {name}."


def _contains_performance_promise(text: str) -> bool:
    lowered = text.lower()
    promise_phrases = (
        "guaranteed",
        "guarantees",
        "will outperform",
        "will beat",
        "can't lose",
        "cannot lose",
        "risk-free",
        "sure profit",
    )
    return any(phrase in lowered for phrase in promise_phrases)


def _format_translation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first_error = exc.errors()[0]
        location = ".".join(str(part) for part in first_error.get("loc", []))
        message = first_error.get("msg", "Invalid LLM translation output")
        if location:
            return f"LLM translation output was invalid at {location}: {message}."
        return f"LLM translation output was invalid: {message}."
    return str(exc)


def _contract_provider_name(contract: LlmStructuredTranslationOutput) -> str:
    provider = contract.provider_metadata.get("provider")
    return str(provider) if provider else LLM_PROVIDER


def _log_provider_validation_failure(
    *,
    provider: str,
    exc: Exception,
    provider_output: Any | None = None,
) -> None:
    location = _validation_error_location(exc)
    output_chars = (
        len(provider_output)
        if isinstance(provider_output, str)
        else len(_json_for_log(provider_output))
        if provider_output is not None
        else 0
    )
    logger.warning(
        "Strategy translation provider output failed validation provider=%s location=%s error=%s output_chars=%s",
        provider,
        location or "<unknown>",
        _truncate_for_log(str(exc)),
        output_chars,
    )


def _validation_error_location(exc: Exception) -> str | None:
    if isinstance(exc, ValidationError):
        first_error = exc.errors()[0]
        loc = first_error.get("loc", [])
        return ".".join(str(part) for part in loc) if loc else None

    match = re.search(r"because (?P<location>.+?) was invalid:", str(exc))
    if match:
        return match.group("location")
    return None


def _json_for_log(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _truncate_for_log(value: str, *, limit: int = 2000) -> str:
    sanitized = _redact_sensitive_values(value).replace("\n", "\\n")
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[: limit - 3] + "..."


def _provider_guidance_result(
    *,
    message: str,
    provider: str,
    mode: str,
    llm_enabled: bool,
    max_backtest_years: int,
    diagnostics: dict[str, Any] | None = None,
) -> StrategyTranslationResult:
    response = _build_response(
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
    return StrategyTranslationResult(
        response=response,
        translation_provider=provider,
        translation_mode=mode,
        llm_enabled=llm_enabled,
        validation_errors=[message],
        diagnostics=diagnostics or {},
    )


def _openai_translation_instructions() -> str:
    return (
        "You translate natural-language ETF strategy requests into structured JSON "
        "matching the provided schema. Strategy V2 JSON is the only executable form. "
        "Do not write or execute code, call tools, simulate returns, or make promises "
        "of profit or future performance. Use only supported tradable and reference "
        "symbols supplied in the request context. Do not invent unsupported indicators, "
        "fields, assets, or strategy semantics. If the request needs unsupported "
        "features or unsupported symbols, return action='guidance' or include them in "
        "unsupported_features instead of inventing config fields. For create_config, "
        "return a COMPLETE Strategy V2 full_config; do not return only a rotation "
        "block. tradable_symbol is required even for rotation configs; use the first "
        "rotation universe symbol if needed. benchmark_symbol is required; default "
        "to SPY for multi-asset rotation unless the user says otherwise. "
        "reference_symbols should include rotation universe symbols except "
        "tradable_symbol, plus benchmark, fallback, and risk-filter symbols when "
        "needed. start_date and end_date are required; use the platform default "
        "date range in context if the user does not specify dates. risk and "
        "core_overlay are required; use safe disabled/default values. Use no "
        "unsupported fields. For edit_config, return either a complete full_config "
        "or a minimal config_patch against current_config."
    )


def _openai_translation_context(request: StrategyTranslationRequest) -> dict[str, Any]:
    default_start_date, default_end_date = _platform_default_date_range(
        max_backtest_years=request.max_backtest_years,
    )
    return {
        "prompt": request.prompt,
        "current_config": request.current_config,
        "context_mode": request.context_mode,
        "max_backtest_years": request.max_backtest_years,
        "platform_default_date_range": {
            "start_date": default_start_date,
            "end_date": default_end_date,
        },
        "user_entitlements": request.user_entitlements,
        "supported_symbols": list(request.supported_symbols),
        "supported_reference_symbols": list(request.supported_reference_symbols),
        "contract_notes": {
            "actions": ["create_config", "edit_config", "guidance"],
            "config_rule": "Return declarative Strategy V2 JSON only; backend validation is mandatory.",
            "unsupported_rule": "Unsupported requests should become guidance, not invented fields.",
            "create_config_required_fields": [
                "schema_version",
                "name",
                "tradable_symbol",
                "benchmark_symbol",
                "reference_symbols",
                "start_date",
                "end_date",
                "initial_capital",
                "transaction_cost_bps",
                "risk",
                "core_overlay",
            ],
            "rotation_required_fields": [
                "rotation.enabled=true",
                "rotation.universe",
                "rotation.ranking",
                "rotation.rebalance",
                "rotation.selection",
                "rotation.allocation",
                "rotation.risk_filter",
                "rotation.fallback",
            ],
            "compact_rotation_example": {
                "schema_version": "2.0",
                "name": "QQQ SPY XLK TLT 63-day Top 1 Rotation",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "SPY",
                "reference_symbols": ["SPY", "XLK", "TLT"],
                "start_date": default_start_date,
                "end_date": default_end_date,
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
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
                    "selection": {"top_n": 1},
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
                    "fallback": {"type": "asset", "symbol": "TLT"},
                },
            },
        },
    }


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    if isinstance(response, dict):
        payload = response
    elif hasattr(response, "model_dump"):
        payload = response.model_dump()
    else:
        payload = response

    texts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return "\n".join(texts).strip()


def _extract_openai_usage_metadata(response: Any) -> dict[str, int | None]:
    if isinstance(response, dict):
        payload = response
    elif hasattr(response, "model_dump"):
        payload = response.model_dump()
    else:
        payload = response

    usage = None
    if isinstance(payload, dict):
        usage = payload.get("usage")
    else:
        usage = getattr(payload, "usage", None)

    if usage is None:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    def read_int(*names: str) -> int | None:
        for name in names:
            if isinstance(usage, dict):
                value = usage.get(name)
            else:
                value = getattr(usage, name, None)
            if isinstance(value, int):
                return value
        return None

    input_tokens = read_int("input_tokens", "prompt_tokens")
    output_tokens = read_int("output_tokens", "completion_tokens")
    total_tokens = read_int("total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _estimate_openai_cost_usd(usage_metadata: dict[str, Any]) -> float | None:
    settings = get_settings()
    input_rate = settings.openai_cost_per_1k_input_tokens_usd
    output_rate = settings.openai_cost_per_1k_output_tokens_usd
    input_tokens = usage_metadata.get("input_tokens")
    output_tokens = usage_metadata.get("output_tokens")
    if (
        input_rate is None
        or output_rate is None
        or not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
    ):
        return None
    return round((input_tokens / 1000 * input_rate) + (output_tokens / 1000 * output_rate), 6)


def _openai_error_status(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    if "timeout" in name or isinstance(exc, TimeoutError):
        return "timeout"
    return "api_error"


def _openai_usage_status_from_request_status(status: str) -> str:
    if status == "ok":
        return "success"
    if status in {"invalid_contract", "empty_response"}:
        return "validation_error"
    if status == "timeout":
        return "timeout"
    return "provider_error"


def _is_successful_deterministic_result(
    result: StrategyTranslationResult,
    *,
    request: StrategyTranslationRequest,
) -> tuple[bool, str | None]:
    response = result.response
    response_type = response.get("response_type")
    if isinstance(response_type, StrategyBuilderResponseType):
        response_type_value = response_type.value
    else:
        response_type_value = str(response_type)
    if response_type_value not in {
        StrategyBuilderResponseType.CREATE_DRAFT.value,
        StrategyBuilderResponseType.UPDATE_DRAFT.value,
    }:
        return False, f"response_type={response_type_value}"

    config = response.get("config")
    if not isinstance(config, dict):
        return False, "missing_config"

    try:
        validate_strategy_builder_request(
            prompt=request.prompt,
            config=config,
            max_backtest_years=request.max_backtest_years,
        )
        StrategyV2.model_validate(config)
    except (ValidationError, ValueError) as exc:
        return False, _format_translation_error(exc)

    return True, None


def _is_non_fallbackable_deterministic_result(
    result: StrategyTranslationResult,
) -> bool:
    response = result.response
    validation_data = response.get("validation_data")
    if isinstance(validation_data, dict):
        validation_type = validation_data.get("validation_type")
        if isinstance(validation_type, StrategyBuilderValidationType):
            validation_type = validation_type.value
        if validation_type == StrategyBuilderValidationType.PLAN_LIMIT.value:
            return True

    answer_data = response.get("answer_data")
    if isinstance(answer_data, dict):
        answer_type = answer_data.get("answer_type")
        if isinstance(answer_type, StrategyBuilderAnswerType):
            answer_type = answer_type.value
        if answer_type == StrategyBuilderAnswerType.PLAN_LIMITS.value:
            return True

    return False


def _openai_block_message(request: StrategyTranslationRequest) -> str:
    if request.openai_block_reason == "prompt_too_long":
        return (
            "AI fallback was not used because this prompt exceeds the OpenAI "
            "fallback character limit. The deterministic Strategy Builder response "
            "is shown instead."
        )
    return (
        "AI fallback was not used because your OpenAI fallback limit was reached "
        "for today. The deterministic Strategy Builder response is shown instead."
    )


def _with_ai_fallback_blocked_note(
    response: dict[str, Any],
    *,
    request: StrategyTranslationRequest,
) -> dict[str, Any]:
    noted = deepcopy(response)
    note = _openai_block_message(request)
    warnings = noted.get("warnings")
    if isinstance(warnings, list):
        if note not in warnings:
            warnings.append(note)
    else:
        noted["warnings"] = [note]

    message = noted.get("message")
    if isinstance(message, str) and note not in message:
        noted["message"] = f"{message} {note}"
    return noted


def _with_ai_unavailable_note(response: dict[str, Any]) -> dict[str, Any]:
    noted = deepcopy(response)
    note = (
        "AI fallback is unavailable because OpenAI is not configured. "
        "The deterministic Strategy Builder response is shown instead."
    )
    warnings = noted.get("warnings")
    if isinstance(warnings, list):
        if note not in warnings:
            warnings.append(note)
    else:
        noted["warnings"] = [note]

    message = noted.get("message")
    if isinstance(message, str) and note not in message:
        noted["message"] = f"{message} {note}"
    return noted


def _with_hybrid_metadata(
    result: StrategyTranslationResult,
    *,
    fallback_used: bool,
    openai_attempted: bool,
    diagnostics: dict[str, Any],
) -> StrategyTranslationResult:
    response = result.response_payload()
    response["translation_mode"] = HYBRID_PROVIDER
    response["translation_fallback_used"] = fallback_used
    response["primary_provider"] = DETERMINISTIC_PROVIDER
    response["deterministic_attempted"] = True
    response["openai_attempted"] = openai_attempted
    if fallback_used:
        response["fallback_provider"] = OPENAI_PROVIDER
    else:
        response.pop("fallback_provider", None)
    return StrategyTranslationResult(
        response=response,
        translation_provider=result.translation_provider,
        translation_mode=HYBRID_PROVIDER,
        llm_enabled=result.llm_enabled,
        validation_errors=result.validation_errors,
        diagnostics=diagnostics,
    )


def _with_provider_metadata(result: StrategyTranslationResult) -> StrategyTranslationResult:
    response = result.response_payload()
    return StrategyTranslationResult(
        response=response,
        translation_provider=result.translation_provider,
        translation_mode=result.translation_mode,
        llm_enabled=result.llm_enabled,
        validation_errors=result.validation_errors,
        diagnostics=result.diagnostics,
    )


def _entitlements_snapshot(entitlements: Any) -> dict[str, Any]:
    if hasattr(entitlements, "__dataclass_fields__"):
        return asdict(entitlements)
    if isinstance(entitlements, dict):
        return dict(entitlements)
    return {}


__all__ = [
    "DETERMINISTIC_PROVIDER",
    "HYBRID_PROVIDER",
    "LLM_PROVIDER",
    "OPENAI_PROVIDER",
    "DeterministicTranslationProvider",
    "HybridStrategyTranslationProvider",
    "LlmStructuredTranslationOutput",
    "LlmTranslationProvider",
    "OpenAIStrategyTranslationProvider",
    "StrategyTranslationProvider",
    "StrategyTranslationProviderUnavailable",
    "StrategyTranslationRequest",
    "StrategyTranslationResult",
    "build_strategy_builder_response_from_llm_contract",
    "build_strategy_translation_request",
    "log_strategy_builder_openai_usage",
    "log_strategy_builder_timing",
    "normalize_translated_strategy_config",
    "select_strategy_translation_provider",
    "translate_strategy_builder_request",
]
