from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from market_simulator.repositories.plans import (
    count_runs_created_today,
    count_saved_strategies,
    get_active_subscription_with_plan,
)


@dataclass
class UserEntitlements:
    plan_code: str
    plan_name: str
    daily_free_runs: int
    max_saved_strategies: int
    max_tracked_strategies: int
    allow_portfolio_runs: bool
    allow_comparison_runs: bool
    allow_parameter_sweeps: bool
    allow_ai_builder: bool
    allow_strategy_history: bool


def get_user_entitlements(db: Session, user_id: str) -> UserEntitlements:
    row = get_active_subscription_with_plan(db, user_id)
    if row is None:
        raise HTTPException(status_code=403, detail="No active subscription plan found")

    _, plan = row

    return UserEntitlements(
        plan_code=plan.code,
        plan_name=plan.name,
        daily_free_runs=plan.daily_free_runs,
        max_saved_strategies=plan.max_saved_strategies,
        max_tracked_strategies=plan.max_tracked_strategies,
        allow_portfolio_runs=plan.allow_portfolio_runs,
        allow_comparison_runs=plan.allow_comparison_runs,
        allow_parameter_sweeps=plan.allow_parameter_sweeps,
        allow_ai_builder=plan.allow_ai_builder,
        allow_strategy_history=plan.allow_strategy_history,
    )


def enforce_builder_access(db: Session, user_id: str) -> UserEntitlements:
    entitlements = get_user_entitlements(db, user_id)
    if not entitlements.allow_ai_builder:
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include strategy builder access",
        )
    return entitlements


def enforce_strategy_create_access(db: Session, user_id: str) -> UserEntitlements:
    entitlements = get_user_entitlements(db, user_id)

    current_saved = count_saved_strategies(db, user_id)
    if current_saved >= entitlements.max_saved_strategies:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Saved strategy limit reached for plan {entitlements.plan_code} "
                f"({entitlements.max_saved_strategies})"
            ),
        )

    return entitlements


def enforce_strategy_history_access(db: Session, user_id: str) -> UserEntitlements:
    entitlements = get_user_entitlements(db, user_id)
    if not entitlements.allow_strategy_history:
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include strategy version history",
        )
    return entitlements


def enforce_run_create_access(db: Session, user_id: str, run_type: str) -> UserEntitlements:
    entitlements = get_user_entitlements(db, user_id)

    if run_type == "PORTFOLIO" and not entitlements.allow_portfolio_runs:
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include portfolio runs",
        )

    if run_type == "COMPARISON" and not entitlements.allow_comparison_runs:
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include comparison runs",
        )

    if run_type == "PARAMETER_SWEEP" and not entitlements.allow_parameter_sweeps:
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include parameter sweeps",
        )

    runs_today = count_runs_created_today(db, user_id)
    if runs_today >= entitlements.daily_free_runs:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Daily run limit reached for plan {entitlements.plan_code} "
                f"({entitlements.daily_free_runs}/day)"
            ),
        )

    return entitlements