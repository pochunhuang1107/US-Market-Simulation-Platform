from __future__ import annotations

import os

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from market_simulator.settings import get_settings
from market_simulator.repositories.plans import (
    count_runs_created_today,
    count_saved_strategies,
    get_active_subscription_with_plan,
)


DEFAULT_MAX_COMPARISON_RUNS = 4
ADVANCED_ROTATION_LIMIT_CODE = "PLAN_LIMIT_CUSTOM_ROTATION"
ADVANCED_ROTATION_MESSAGE = "Custom rotation strategies require Research access."
ADVANCED_ROTATION_GUIDANCE = (
    "You can still run curated Gallery examples within your plan limits. "
    "This is a plan limit, not a strategy validation error."
)
MODEL_SIGNAL_ACCESS_LIMIT_DETAIL = {
    "code": "PLAN_LIMIT_MODEL_SIGNALS",
    "message": "Model-signal catalog access requires advanced research access.",
    "guidance": (
        "These entries are research candidates and are not available on the "
        "free plan."
    ),
    "plan_limit": True,
}


@dataclass
class UserEntitlements:
    plan_code: str
    plan_name: str
    monthly_price_usd: float
    daily_free_runs: int
    max_saved_strategies: int
    max_tracked_strategies: int
    builder_prompt_daily_limit: int
    builder_prompt_max_chars: int
    max_backtest_years: int
    max_comparison_runs: int
    allow_portfolio_runs: bool
    allow_comparison_runs: bool
    allow_parameter_sweeps: bool
    allow_ai_builder: bool
    allow_strategy_history: bool
    allow_rotation_templates: bool
    allow_custom_rotation: bool
    allow_rotation_edit: bool
    allow_advanced_builder: bool


def _get_dev_admin_override_entitlements(user_id: str) -> UserEntitlements | None:
    settings = get_settings()

    if os.getenv("PYTEST_CURRENT_TEST"):
        return None

    if settings.env != "local":
        return None

    if not settings.enable_dev_admin_override:
        return None

    if user_id not in settings.dev_admin_user_ids:
        return None

    return UserEntitlements(
        plan_code="DEV_ADMIN",
        plan_name="Developer Admin",
        monthly_price_usd=settings.dev_admin_monthly_price_usd,
        daily_free_runs=settings.dev_admin_daily_free_runs,
        max_saved_strategies=settings.dev_admin_max_saved_strategies,
        max_tracked_strategies=settings.dev_admin_max_tracked_strategies,
        builder_prompt_daily_limit=settings.dev_admin_builder_prompt_daily_limit,
        builder_prompt_max_chars=settings.dev_admin_builder_prompt_max_chars,
        max_backtest_years=settings.dev_admin_max_backtest_years,
        max_comparison_runs=DEFAULT_MAX_COMPARISON_RUNS,
        allow_portfolio_runs=True,
        allow_comparison_runs=True,
        allow_parameter_sweeps=True,
        allow_ai_builder=True,
        allow_strategy_history=True,
        allow_rotation_templates=True,
        allow_custom_rotation=True,
        allow_rotation_edit=True,
        allow_advanced_builder=True,
    )


def get_user_entitlements(db: Session, user_id: str) -> UserEntitlements:
    override = _get_dev_admin_override_entitlements(user_id)
    if override is not None:
        return override

    row = get_active_subscription_with_plan(db, user_id)
    if row is None:
        raise HTTPException(status_code=403, detail="No active subscription plan found")

    _, plan = row

    return UserEntitlements(
        plan_code=plan.code,
        plan_name=plan.name,
        monthly_price_usd=float(plan.monthly_price_usd),
        daily_free_runs=plan.daily_free_runs,
        max_saved_strategies=plan.max_saved_strategies,
        max_tracked_strategies=plan.max_tracked_strategies,
        builder_prompt_daily_limit=plan.builder_prompt_daily_limit,
        builder_prompt_max_chars=plan.builder_prompt_max_chars,
        max_backtest_years=plan.max_backtest_years,
        max_comparison_runs=getattr(plan, "max_comparison_runs", DEFAULT_MAX_COMPARISON_RUNS),
        allow_portfolio_runs=plan.allow_portfolio_runs,
        allow_comparison_runs=plan.allow_comparison_runs,
        allow_parameter_sweeps=plan.allow_parameter_sweeps,
        allow_ai_builder=plan.allow_ai_builder,
        allow_strategy_history=plan.allow_strategy_history,
        allow_rotation_templates=getattr(plan, "allow_rotation_templates", False),
        allow_custom_rotation=getattr(plan, "allow_custom_rotation", False),
        allow_rotation_edit=getattr(plan, "allow_rotation_edit", False),
        allow_advanced_builder=getattr(plan, "allow_advanced_builder", False),
    )


def is_rotation_enabled_config(config: dict | None) -> bool:
    if not isinstance(config, dict):
        return False
    rotation = config.get("rotation")
    return isinstance(rotation, dict) and rotation.get("enabled") is True


def is_curated_gallery_run_payload(request_payload: dict | None) -> bool:
    if not isinstance(request_payload, dict):
        return False

    return (
        request_payload.get("source") == "strategy_gallery"
        and isinstance(request_payload.get("template_id"), str)
        and bool(request_payload.get("template_id", "").strip())
        and isinstance(request_payload.get("template_title"), str)
        and bool(request_payload.get("template_title", "").strip())
    )


def advanced_rotation_limit_detail() -> dict[str, str | bool]:
    return {
        "code": ADVANCED_ROTATION_LIMIT_CODE,
        "message": ADVANCED_ROTATION_MESSAGE,
        "guidance": ADVANCED_ROTATION_GUIDANCE,
        "plan_limit": True,
    }


def advanced_rotation_limit_message() -> str:
    return f"{ADVANCED_ROTATION_MESSAGE} {ADVANCED_ROTATION_GUIDANCE}"


def enforce_custom_rotation_access_for_config(
    entitlements: UserEntitlements,
    *,
    config: dict | None,
    current_config: dict | None = None,
    request_payload: dict | None = None,
    require_advanced_builder: bool = False,
) -> None:
    if not is_rotation_enabled_config(config):
        return

    if is_curated_gallery_run_payload(request_payload) and entitlements.allow_rotation_templates:
        return

    is_editing_rotation = is_rotation_enabled_config(current_config)
    allowed = entitlements.allow_rotation_edit if is_editing_rotation else entitlements.allow_custom_rotation
    if allowed and (not require_advanced_builder or entitlements.allow_advanced_builder):
        return

    raise HTTPException(status_code=403, detail=advanced_rotation_limit_detail())


def enforce_builder_access(db: Session, user_id: str) -> UserEntitlements:
    entitlements = get_user_entitlements(db, user_id)
    if not entitlements.allow_ai_builder:
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include strategy builder access",
        )
    return entitlements


def enforce_comparison_run_limit(
    db: Session,
    user_id: str,
    requested_run_count: int,
) -> UserEntitlements:
    entitlements = get_user_entitlements(db, user_id)
    if not entitlements.allow_comparison_runs:
        raise HTTPException(
            status_code=403,
            detail="Your current plan does not include comparison runs",
        )

    if requested_run_count > entitlements.max_comparison_runs:
        raise HTTPException(
            status_code=403,
            detail=f"Comparison limit reached for your plan. Select up to {entitlements.max_comparison_runs} runs.",
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


def enforce_model_signal_access(db: Session, user_id: str) -> UserEntitlements:
    entitlements = get_user_entitlements(db, user_id)
    if not entitlements.allow_advanced_builder:
        raise HTTPException(status_code=403, detail=MODEL_SIGNAL_ACCESS_LIMIT_DETAIL)
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
