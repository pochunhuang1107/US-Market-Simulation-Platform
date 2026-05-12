from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderGenerateRequest,
    StrategyBuilderGenerateResponse,
    StrategyBuilderResponseType,
)
from market_simulator.repositories.builder_prompts import (
    count_builder_prompts_today,
    create_builder_prompt_event,
)
from market_simulator.repositories.openai_usage import (
    count_openai_usage_today,
    create_openai_usage_event,
)
from market_simulator.services.entitlements import (
    advanced_rotation_limit_message,
    enforce_custom_rotation_access_for_config,
    get_user_entitlements,
)
from market_simulator.services.strategy_builder_guardrails import (
    validate_strategy_builder_request,
)
from market_simulator.services.strategy_builder_service import (
    build_validation_data,
    detect_custom_rotation_builder_intent,
)
from market_simulator.services.strategy_translation import (
    log_strategy_builder_openai_usage,
    log_strategy_builder_timing,
    translate_strategy_builder_request,
)
from market_simulator.settings import get_settings

router = APIRouter(prefix="/strategy-builder", tags=["strategy-builder"])


def _record_rejected_prompt(
    db: Session,
    *,
    user_id: str,
    prompt_chars: int,
    reason: str,
) -> None:
    create_builder_prompt_event(
        db,
        user_id=user_id,
        prompt_chars=prompt_chars,
        status="REJECTED",
        rejection_reason=reason[:255],
    )


def _structured_builder_limit_response(
    *,
    status_code: int,
    message: str,
    max_backtest_years: int,
    translation_provider: str = "deterministic",
    translation_mode: str = "deterministic",
    translation_fallback_used: bool = False,
    primary_provider: str | None = None,
    fallback_provider: str | None = None,
    deterministic_attempted: bool = False,
    openai_attempted: bool = False,
    llm_enabled: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "detail": message,
                "response_type": StrategyBuilderResponseType.VALIDATION_ERROR,
                "message": message,
                "config": None,
                "summary": None,
                "warnings": [],
                "assumptions": [],
                "changes": [],
                "answer_data": None,
                "validation_data": build_validation_data(
                    message=message,
                    max_backtest_years=max_backtest_years,
                ),
                "guidance_data": None,
                "sweep_draft": None,
                "translation_provider": translation_provider,
                "translation_mode": translation_mode,
                "translation_fallback_used": translation_fallback_used,
                "primary_provider": primary_provider,
                "fallback_provider": fallback_provider,
                "deterministic_attempted": deterministic_attempted,
                "openai_attempted": openai_attempted,
                "llm_enabled": llm_enabled,
            }
        ),
    )


def _translation_metadata(result: dict) -> dict[str, Any]:
    return {
        "translation_provider": result.get("translation_provider", "deterministic"),
        "translation_mode": result.get("translation_mode", "deterministic"),
        "translation_fallback_used": bool(
            result.get("translation_fallback_used", False)
        ),
        "primary_provider": result.get("primary_provider"),
        "fallback_provider": result.get("fallback_provider"),
        "deterministic_attempted": bool(
            result.get("deterministic_attempted", False)
        ),
        "openai_attempted": bool(result.get("openai_attempted", False)),
        "llm_enabled": bool(result.get("llm_enabled", False)),
    }


def _parse_plan_limit_value(value: str) -> int | None:
    normalized = value.strip().lower()
    if normalized in {"", "none", "null", "unlimited", "-1"}:
        return None
    return int(normalized)


def _openai_fallback_limit_for_plan(plan_code: str) -> int | None:
    settings = get_settings()
    plan_code = plan_code.strip().upper()
    for item in settings.openai_fallback_daily_limit_by_plan.split(","):
        if ":" not in item:
            continue
        code, value = item.split(":", 1)
        if code.strip().upper() == plan_code:
            return _parse_plan_limit_value(value)
    return settings.openai_fallback_daily_limit_per_user


def _openai_guard(
    db: Session,
    *,
    user_id: str,
    plan_code: str,
    prompt_chars: int,
) -> dict[str, Any]:
    settings = get_settings()
    max_prompt_chars = settings.openai_fallback_max_prompt_chars
    if max_prompt_chars is not None and prompt_chars > max_prompt_chars:
        return {
            "allowed": False,
            "reason": "prompt_too_long",
            "limit": max_prompt_chars,
            "used_today": None,
        }

    daily_limit = _openai_fallback_limit_for_plan(plan_code)
    if daily_limit is None:
        return {
            "allowed": True,
            "reason": None,
            "limit": None,
            "used_today": None,
        }

    used_today = count_openai_usage_today(db, user_id)
    return {
        "allowed": used_today < daily_limit,
        "reason": None if used_today < daily_limit else "daily_limit_reached",
        "limit": daily_limit,
        "used_today": used_today,
    }


def _response_type_for_usage(result: dict[str, Any]) -> str | None:
    response_type = result.get("response_type")
    return response_type.value if hasattr(response_type, "value") else response_type


def _openai_usage_mode(result: dict[str, Any]) -> str | None:
    if result.get("translation_provider") != "openai":
        return None
    if result.get("translation_mode") == "hybrid":
        return "hybrid_fallback"
    return "openai_direct"


def _int_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(round(value))
    return None


def _record_openai_usage_if_needed(
    db: Session,
    *,
    user_id: str,
    prompt_chars: int,
    result: dict[str, Any],
    diagnostics: dict[str, Any],
) -> None:
    mode = _openai_usage_mode(result)
    status = diagnostics.get("openai_usage_status")
    if mode is None or not isinstance(status, str):
        return

    fallback_used = bool(result.get("translation_fallback_used", False))
    event = create_openai_usage_event(
        db,
        user_id=user_id,
        provider="openai",
        mode=mode,
        model=diagnostics.get("model") or get_settings().openai_model,
        prompt_chars=prompt_chars,
        response_chars=diagnostics.get("response_chars"),
        status=status,
        duration_ms=_int_ms(diagnostics.get("openai_provider_ms")),
        fallback_used=fallback_used,
        response_type=_response_type_for_usage(result),
        input_tokens=diagnostics.get("input_tokens"),
        output_tokens=diagnostics.get("output_tokens"),
        total_tokens=diagnostics.get("total_tokens"),
        estimated_cost_usd=diagnostics.get("estimated_cost_usd"),
    )
    log_strategy_builder_openai_usage(
        user_id=user_id,
        event_id=event.id,
        provider="openai",
        mode=mode,
        model=event.model,
        fallback_used=fallback_used,
        status=status,
        duration_ms=event.duration_ms,
        prompt_chars=prompt_chars,
        response_chars=event.response_chars,
        response_type=event.response_type,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        total_tokens=event.total_tokens,
        estimated_cost_usd=event.estimated_cost_usd,
    )


@router.post("/generate", response_model=StrategyBuilderGenerateResponse)
def generate_strategy_draft_api(
    req: StrategyBuilderGenerateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    pre_translation_start = time.perf_counter()
    entitlements = get_user_entitlements(db, user["id"])
    prompt_chars = len(req.prompt)

    if not entitlements.allow_ai_builder:
        _record_rejected_prompt(
            db,
            user_id=user["id"],
            prompt_chars=prompt_chars,
            reason="BUILDER_NOT_ALLOWED",
        )
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include strategy builder access",
        )

    prompts_used_today = count_builder_prompts_today(db, user["id"])
    if prompts_used_today >= entitlements.builder_prompt_daily_limit:
        _record_rejected_prompt(
            db,
            user_id=user["id"],
            prompt_chars=prompt_chars,
            reason="DAILY_PROMPT_LIMIT_REACHED",
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"Daily builder prompt limit reached for plan {entitlements.plan_code} "
                f"({entitlements.builder_prompt_daily_limit}/day)"
            ),
        )

    if prompt_chars > entitlements.builder_prompt_max_chars:
        _record_rejected_prompt(
            db,
            user_id=user["id"],
            prompt_chars=prompt_chars,
            reason="PROMPT_TOO_LONG",
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Prompt exceeds your plan limit of "
                f"{entitlements.builder_prompt_max_chars} characters"
            ),
        )

    if detect_custom_rotation_builder_intent(req):
        current_config = req.context.current_config if req.context else None
        try:
            enforce_custom_rotation_access_for_config(
                entitlements,
                config={"rotation": {"enabled": True}},
                current_config=current_config if isinstance(current_config, dict) else None,
                require_advanced_builder=True,
            )
        except HTTPException:
            message = advanced_rotation_limit_message()
            _record_rejected_prompt(
                db,
                user_id=user["id"],
                prompt_chars=prompt_chars,
                reason="CUSTOM_ROTATION_NOT_ALLOWED",
            )
            return _structured_builder_limit_response(
                status_code=403,
                message=message,
                max_backtest_years=entitlements.max_backtest_years,
            )

    log_strategy_builder_timing(
        "strategy_builder.entitlements",
        stage="pre_translation",
        total_ms=round((time.perf_counter() - pre_translation_start) * 1000, 2),
        prompt_chars=prompt_chars,
        max_backtest_years=entitlements.max_backtest_years,
    )

    openai_guard = _openai_guard(
        db,
        user_id=user["id"],
        plan_code=entitlements.plan_code,
        prompt_chars=prompt_chars,
    )
    translation_result = translate_strategy_builder_request(
        req,
        entitlements=entitlements,
        max_backtest_years=entitlements.max_backtest_years,
        openai_allowed=bool(openai_guard["allowed"]),
        openai_block_reason=openai_guard["reason"],
        openai_limit=openai_guard["limit"],
        openai_used_today=openai_guard["used_today"],
    )
    result = translation_result.response_payload()
    _record_openai_usage_if_needed(
        db,
        user_id=user["id"],
        prompt_chars=prompt_chars,
        result=result,
        diagnostics=translation_result.diagnostics,
    )

    result_config = result.get("config") if isinstance(result.get("config"), dict) else None
    current_config = req.context.current_config if req.context else None
    if result_config is not None:
        try:
            enforce_custom_rotation_access_for_config(
                entitlements,
                config=result_config,
                current_config=current_config if isinstance(current_config, dict) else None,
                require_advanced_builder=True,
            )
        except HTTPException:
            message = advanced_rotation_limit_message()
            _record_rejected_prompt(
                db,
                user_id=user["id"],
                prompt_chars=prompt_chars,
                reason="CUSTOM_ROTATION_NOT_ALLOWED",
            )
            return _structured_builder_limit_response(
                status_code=403,
                message=message,
                max_backtest_years=entitlements.max_backtest_years,
                **_translation_metadata(result),
            )

    sweep_draft = result.get("sweep_draft") if isinstance(result.get("sweep_draft"), dict) else None
    sweep_base_config = sweep_draft.get("base_config") if isinstance(sweep_draft, dict) else None
    if isinstance(sweep_base_config, dict):
        try:
            enforce_custom_rotation_access_for_config(
                entitlements,
                config=sweep_base_config,
                current_config=current_config if isinstance(current_config, dict) else None,
                require_advanced_builder=True,
            )
        except HTTPException:
            message = advanced_rotation_limit_message()
            _record_rejected_prompt(
                db,
                user_id=user["id"],
                prompt_chars=prompt_chars,
                reason="CUSTOM_ROTATION_NOT_ALLOWED",
            )
            return _structured_builder_limit_response(
                status_code=403,
                message=message,
                max_backtest_years=entitlements.max_backtest_years,
                **_translation_metadata(result),
            )

    if (
        result["response_type"] == StrategyBuilderResponseType.PARAMETER_SWEEP_DRAFT
        and not entitlements.allow_parameter_sweeps
    ):
        message = (
            "Your current plan does not include parameter sweeps. "
            "This is a plan limit, not a strategy validation error."
        )
        _record_rejected_prompt(
            db,
            user_id=user["id"],
            prompt_chars=prompt_chars,
            reason="PARAMETER_SWEEP_NOT_ALLOWED",
        )
        return _structured_builder_limit_response(
            status_code=403,
            message=message,
            max_backtest_years=entitlements.max_backtest_years,
            **_translation_metadata(result),
        )

    if (
        result["response_type"]
        in {
            StrategyBuilderResponseType.CREATE_DRAFT,
            StrategyBuilderResponseType.UPDATE_DRAFT,
        }
        and result.get("config") is not None
    ):
        guardrail_start = time.perf_counter()
        try:
            validate_strategy_builder_request(
                prompt=req.prompt,
                config=result["config"],
                max_backtest_years=entitlements.max_backtest_years,
            )
        except ValueError as exc:
            log_strategy_builder_timing(
                "strategy_builder.router_validation",
                provider=result.get("translation_provider", "deterministic"),
                mode=result.get("translation_mode", "deterministic"),
                guardrail_ms=round(
                    (time.perf_counter() - guardrail_start) * 1000,
                    2,
                ),
                status="invalid_config",
            )
            message = str(exc)

            _record_rejected_prompt(
                db,
                user_id=user["id"],
                prompt_chars=prompt_chars,
                reason=message,
            )

            return JSONResponse(
                status_code=400,
                content=jsonable_encoder(
                    {
                        "detail": message,
                        "response_type": StrategyBuilderResponseType.VALIDATION_ERROR,
                        "message": message,
                        "config": None,
                        "summary": None,
                        "warnings": [],
                        "assumptions": [],
                        "changes": [],
                        "answer_data": None,
                        "validation_data": build_validation_data(
                            message=message,
                            max_backtest_years=entitlements.max_backtest_years,
                        ),
                        "guidance_data": None,
                        "sweep_draft": None,
                        **_translation_metadata(result),
                    }
                ),
            )
        else:
            log_strategy_builder_timing(
                "strategy_builder.router_validation",
                provider=result.get("translation_provider", "deterministic"),
                mode=result.get("translation_mode", "deterministic"),
                guardrail_ms=round(
                    (time.perf_counter() - guardrail_start) * 1000,
                    2,
                ),
                status="ok",
            )

    if result["response_type"] == StrategyBuilderResponseType.PARAMETER_SWEEP_DRAFT:
        sweep_draft = result.get("sweep_draft") or {}
        base_config = sweep_draft.get("base_config") if isinstance(sweep_draft, dict) else None
        if isinstance(base_config, dict):
            try:
                validate_strategy_builder_request(
                    prompt=req.prompt,
                    config=base_config,
                    max_backtest_years=entitlements.max_backtest_years,
                )
            except ValueError as exc:
                message = str(exc)

                _record_rejected_prompt(
                    db,
                    user_id=user["id"],
                    prompt_chars=prompt_chars,
                    reason=message,
                )

                return JSONResponse(
                    status_code=400,
                    content=jsonable_encoder(
                        {
                            "detail": message,
                            "response_type": StrategyBuilderResponseType.VALIDATION_ERROR,
                            "message": message,
                            "config": None,
                            "summary": None,
                            "warnings": [],
                            "assumptions": [],
                            "changes": [],
                            "answer_data": None,
                            "validation_data": build_validation_data(
                                message=message,
                                max_backtest_years=entitlements.max_backtest_years,
                            ),
                            "guidance_data": None,
                            "sweep_draft": None,
                            **_translation_metadata(result),
                        }
                    ),
                )

    create_builder_prompt_event(
        db,
        user_id=user["id"],
        prompt_chars=prompt_chars,
        status="ACCEPTED",
        rejection_reason=None,
    )

    return StrategyBuilderGenerateResponse(**result)
