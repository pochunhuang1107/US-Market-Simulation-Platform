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
    get_active_subscription_with_plan,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/entitlements", response_model=MeEntitlementsResponse)
def get_my_entitlements(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db_user = db.query(User).filter(User.id == user["id"]).first()
    if db_user is None:
        raise HTTPException(status_code=401, detail="User not found")

    row = get_active_subscription_with_plan(db, user["id"])
    if row is None:
        raise HTTPException(status_code=403, detail="No active subscription plan found")

    _, plan = row

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
            code=plan.code,
            name=plan.name,
            monthly_price_usd=float(plan.monthly_price_usd),
        ),
        features=MeFeatureFlagsResponse(
            allow_portfolio_runs=plan.allow_portfolio_runs,
            allow_comparison_runs=plan.allow_comparison_runs,
            allow_parameter_sweeps=plan.allow_parameter_sweeps,
            allow_ai_builder=plan.allow_ai_builder,
            allow_strategy_history=plan.allow_strategy_history,
        ),
        limits=MeUsageLimitsResponse(
            daily_free_runs=plan.daily_free_runs,
            max_saved_strategies=plan.max_saved_strategies,
            max_tracked_strategies=plan.max_tracked_strategies,
            builder_prompt_daily_limit=plan.builder_prompt_daily_limit,
            builder_prompt_max_chars=plan.builder_prompt_max_chars,
            max_backtest_years=plan.max_backtest_years,
        ),
        usage=MeUsageResponse(
            runs_created_today=runs_created_today,
            daily_runs_remaining=max(plan.daily_free_runs - runs_created_today, 0),
            saved_strategies=saved_strategies,
            saved_strategies_remaining=max(plan.max_saved_strategies - saved_strategies, 0),
            tracked_strategies=tracked_strategies,
            tracked_strategies_remaining=max(plan.max_tracked_strategies - tracked_strategies, 0),
            builder_prompts_used_today=builder_prompts_used_today,
            builder_prompts_remaining_today=max(
                plan.builder_prompt_daily_limit - builder_prompts_used_today,
                0,
            ),
        ),
    )