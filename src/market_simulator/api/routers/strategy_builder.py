from __future__ import annotations

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
    generate_strategy_builder_response,
)

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
            }
        ),
    )


@router.post("/generate", response_model=StrategyBuilderGenerateResponse)
def generate_strategy_draft_api(
    req: StrategyBuilderGenerateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
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

    result = generate_strategy_builder_response(
        req,
        max_backtest_years=entitlements.max_backtest_years,
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
        )

    if (
        result["response_type"]
        in {
            StrategyBuilderResponseType.CREATE_DRAFT,
            StrategyBuilderResponseType.UPDATE_DRAFT,
        }
        and result.get("config") is not None
    ):
        try:
            validate_strategy_builder_request(
                prompt=req.prompt,
                config=result["config"],
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
                    }
                ),
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
