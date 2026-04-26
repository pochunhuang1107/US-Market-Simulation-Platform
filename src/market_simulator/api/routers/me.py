from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.me import (
    MeEntitlementsResponse,
    MeFeatureFlagsResponse,
    MePlanResponse,
    MeUsageLimitsResponse,
    MeUsageResponse,
    MeUserResponse,
)
from market_simulator.db.models.user import User
from market_simulator.repositories.builder_prompts import count_builder_prompts_today
from market_simulator.repositories.plans import (
    count_runs_created_today,
    count_saved_strategies,
    count_tracked_strategies,
)
from market_simulator.services.entitlements import get_user_entitlements

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/entitlements", response_model=MeEntitlementsResponse)
def get_my_entitlements(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db_user = db.query(User).filter(User.id == user["id"]).first()
    if db_user is None:
        raise HTTPException(status_code=401, detail="User not found")

    entitlements = get_user_entitlements(db, user["id"])

    runs_created_today = count_runs_created_today(db, user["id"])
    saved_strategies = count_saved_strategies(db, user["id"])
    tracked_strategies = count_tracked_strategies(db, user["id"])
    builder_prompts_used_today = count_builder_prompts_today(db, user["id"])

    return MeEntitlementsResponse(
        user=MeUserResponse(
            id=str(db_user.id),
            email=db_user.email,
            display_name=db_user.display_name,
            status=str(db_user.status),
        ),
        plan=MePlanResponse(
            code=entitlements.plan_code,
            name=entitlements.plan_name,
            monthly_price_usd=entitlements.monthly_price_usd,
        ),
        features=MeFeatureFlagsResponse(
            allow_portfolio_runs=entitlements.allow_portfolio_runs,
            allow_comparison_runs=entitlements.allow_comparison_runs,
            allow_parameter_sweeps=entitlements.allow_parameter_sweeps,
            allow_ai_builder=entitlements.allow_ai_builder,
            allow_strategy_history=entitlements.allow_strategy_history,
        ),
        limits=MeUsageLimitsResponse(
            daily_free_runs=entitlements.daily_free_runs,
            max_saved_strategies=entitlements.max_saved_strategies,
            max_tracked_strategies=entitlements.max_tracked_strategies,
            builder_prompt_daily_limit=entitlements.builder_prompt_daily_limit,
            builder_prompt_max_chars=entitlements.builder_prompt_max_chars,
            max_backtest_years=entitlements.max_backtest_years,
            max_comparison_runs=entitlements.max_comparison_runs,
        ),
        usage=MeUsageResponse(
            runs_created_today=runs_created_today,
            daily_runs_remaining=max(entitlements.daily_free_runs - runs_created_today, 0),
            saved_strategies=saved_strategies,
            saved_strategies_remaining=max(entitlements.max_saved_strategies - saved_strategies, 0),
            tracked_strategies=tracked_strategies,
            tracked_strategies_remaining=max(
                entitlements.max_tracked_strategies - tracked_strategies,
                0,
            ),
            builder_prompts_used_today=builder_prompts_used_today,
            builder_prompts_remaining_today=max(
                entitlements.builder_prompt_daily_limit - builder_prompts_used_today,
                0,
            ),
        ),
    )
