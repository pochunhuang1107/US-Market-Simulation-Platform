from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderGenerateRequest,
    StrategyBuilderGuidanceType,
    StrategyBuilderResponseType,
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
LLM_PROVIDER = "llm"


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


@dataclass(frozen=True)
class StrategyTranslationResult:
    response: dict[str, Any]
    translation_provider: str
    translation_mode: str
    llm_enabled: bool
    validation_errors: list[str]

    def response_payload(self) -> dict[str, Any]:
        payload = dict(self.response)
        payload.setdefault("translation_provider", self.translation_provider)
        payload.setdefault("translation_mode", self.translation_mode)
        payload.setdefault("llm_enabled", self.llm_enabled)
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
        from market_simulator.services.strategy_builder_service import (
            generate_strategy_builder_response,
        )

        response = generate_strategy_builder_response(
            request.raw_request,
            max_backtest_years=request.max_backtest_years,
        )
        return StrategyTranslationResult(
            response=response,
            translation_provider=self.name,
            translation_mode=self.mode,
            llm_enabled=self.llm_enabled,
            validation_errors=[],
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


def build_strategy_translation_request(
    req: StrategyBuilderGenerateRequest,
    *,
    entitlements: Any,
    max_backtest_years: int,
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
    )


def select_strategy_translation_provider(
    *,
    requested_mode: str | None = None,
) -> StrategyTranslationProvider:
    settings = get_settings()
    configured_provider = settings.strategy_builder_provider.strip().lower()
    explicit_mode = (requested_mode or "").strip().lower()
    requested_llm = explicit_mode in {"llm", "ai", "natural_language_llm"}

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
) -> StrategyTranslationResult:
    translation_request = build_strategy_translation_request(
        req,
        entitlements=entitlements,
        max_backtest_years=max_backtest_years,
    )
    selected_provider = provider or select_strategy_translation_provider(
        requested_mode=translation_request.context_mode,
    )
    result = selected_provider.translate(translation_request)
    return _with_provider_metadata(result)


def build_strategy_builder_response_from_llm_contract(
    contract: LlmStructuredTranslationOutput,
    *,
    request: StrategyTranslationRequest,
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
    normalized_config = normalize_translated_strategy_config(
        candidate_config,
        prompt=request.prompt,
        max_backtest_years=request.max_backtest_years,
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
        changes=[],
    )


def normalize_translated_strategy_config(
    config: dict[str, Any],
    *,
    prompt: str,
    max_backtest_years: int,
) -> dict[str, Any]:
    validate_strategy_builder_request(
        prompt=prompt,
        config=config,
        max_backtest_years=max_backtest_years,
    )
    strategy = StrategyV2.model_validate(config)
    return strategy.model_dump(mode="json", exclude_none=True)


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


def _with_provider_metadata(result: StrategyTranslationResult) -> StrategyTranslationResult:
    response = result.response_payload()
    return StrategyTranslationResult(
        response=response,
        translation_provider=result.translation_provider,
        translation_mode=result.translation_mode,
        llm_enabled=result.llm_enabled,
        validation_errors=result.validation_errors,
    )


def _entitlements_snapshot(entitlements: Any) -> dict[str, Any]:
    if hasattr(entitlements, "__dataclass_fields__"):
        return asdict(entitlements)
    if isinstance(entitlements, dict):
        return dict(entitlements)
    return {}


__all__ = [
    "DETERMINISTIC_PROVIDER",
    "LLM_PROVIDER",
    "DeterministicTranslationProvider",
    "LlmStructuredTranslationOutput",
    "LlmTranslationProvider",
    "StrategyTranslationProvider",
    "StrategyTranslationRequest",
    "StrategyTranslationResult",
    "build_strategy_builder_response_from_llm_contract",
    "build_strategy_translation_request",
    "normalize_translated_strategy_config",
    "select_strategy_translation_provider",
    "translate_strategy_builder_request",
]
