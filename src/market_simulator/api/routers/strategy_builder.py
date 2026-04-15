from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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
from market_simulator.services.entitlements import get_user_entitlements
from market_simulator.services.strategy_builder_guardrails import (
    validate_strategy_builder_request,
)
from market_simulator.services.strategy_builder_service import (
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
            _record_rejected_prompt(
                db,
                user_id=user["id"],
                prompt_chars=prompt_chars,
                reason=str(exc),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    create_builder_prompt_event(
        db,
        user_id=user["id"],
        prompt_chars=prompt_chars,
        status="ACCEPTED",
        rejection_reason=None,
    )

    return StrategyBuilderGenerateResponse(**result)