from __future__ import annotations

import sys
import uuid
from decimal import Decimal
from pathlib import Path

from market_simulator.db.enums import SubscriptionStatus
from market_simulator.db.models.user import Plan, User, UserPlanSubscription
from market_simulator.services.entitlements import get_user_entitlements
from market_simulator.services.user_provisioning import provision_user

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_local_dev  # noqa: E402
import seed_plans  # noqa: E402
import seed_user  # noqa: E402
import provision_user as provision_user_script  # noqa: E402


def _create_existing_plan(
    db_session,
    *,
    code: str,
    name: str,
    daily_free_runs: int,
) -> Plan:
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=name,
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=daily_free_runs,
        max_saved_strategies=5,
        max_tracked_strategies=0,
        builder_prompt_daily_limit=20,
        builder_prompt_max_chars=1000,
        max_backtest_years=5,
        max_comparison_runs=4,
        allow_portfolio_runs=False,
        allow_comparison_runs=False,
        allow_parameter_sweeps=False,
        allow_ai_builder=True,
        allow_strategy_history=False,
        is_active=True,
    )
    db_session.add(plan)
    return plan


def test_seed_local_dev_creates_plans_and_default_user(db_session, monkeypatch):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(seed_user, "SessionLocal", lambda: db_session)

    seed_local_dev.seed()

    plan_codes = {plan.code for plan in db_session.query(Plan).all()}
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    subscription = db_session.query(UserPlanSubscription).one()

    assert plan_codes == {"FREE", "PRO", "BETA_TESTER"}
    assert str(user.id) == seed_user.USER_ID
    assert subscription.user_id == user.id


def test_seed_local_dev_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(seed_user, "SessionLocal", lambda: db_session)

    seed_local_dev.seed()
    seed_local_dev.seed()

    assert db_session.query(Plan).count() == 3
    assert db_session.query(User).count() == 1
    assert db_session.query(UserPlanSubscription).count() == 1


def test_seed_plans_adds_missing_beta_without_overwriting_existing_plans(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    free = _create_existing_plan(
        db_session,
        code="FREE",
        name="Custom Free",
        daily_free_runs=42,
    )
    _create_existing_plan(
        db_session,
        code="PRO",
        name="Custom Pro",
        daily_free_runs=84,
    )
    db_session.commit()
    free_id = free.id

    seed_plans.seed()

    plans_by_code = {plan.code: plan for plan in db_session.query(Plan).all()}
    assert set(plans_by_code) == {"FREE", "PRO", "BETA_TESTER"}
    assert plans_by_code["FREE"].id == free_id
    assert plans_by_code["FREE"].name == "Custom Free"
    assert plans_by_code["FREE"].daily_free_runs == 42

    beta = plans_by_code["BETA_TESTER"]
    assert beta.name == "Beta Tester"
    assert beta.daily_free_runs == 999999
    assert beta.max_saved_strategies == 999999
    assert beta.max_tracked_strategies == 999999
    assert beta.allow_parameter_sweeps is True
    assert beta.allow_comparison_runs is True
    assert beta.allow_strategy_history is True


def test_beta_tester_plan_provisions_with_high_entitlements(db_session, monkeypatch):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    seed_plans.seed()

    result = provision_user(
        db_session,
        email="founder@example.com",
        plan_code="BETA_TESTER",
        external_provider="auth0",
        external_subject="google-oauth2|112608715746802455074",
    )

    subscription = db_session.query(UserPlanSubscription).one()
    assert result.plan_code == "BETA_TESTER"
    assert subscription.status == SubscriptionStatus.ACTIVE

    entitlements = get_user_entitlements(db_session, result.user_id)
    assert entitlements.plan_code == "BETA_TESTER"
    assert entitlements.daily_free_runs == 999999
    assert entitlements.max_saved_strategies == 999999
    assert entitlements.max_tracked_strategies == 999999
    assert entitlements.builder_prompt_daily_limit == 999999
    assert entitlements.builder_prompt_max_chars == 20000
    assert entitlements.max_backtest_years == 25
    assert entitlements.max_comparison_runs == 4
    assert entitlements.allow_parameter_sweeps is True
    assert entitlements.allow_comparison_runs is True
    assert entitlements.allow_strategy_history is True


def test_beta_tester_assignment_takes_precedence_over_existing_free_plan(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    seed_plans.seed()
    free_result = provision_user(
        db_session,
        email="founder@example.com",
        plan_code="FREE",
        external_provider="auth0",
        external_subject="google-oauth2|112608715746802455074",
    )

    beta_result = provision_user(
        db_session,
        email="founder@example.com",
        plan_code="BETA_TESTER",
        external_provider="auth0",
        external_subject="google-oauth2|112608715746802455074",
    )

    subscriptions = db_session.query(UserPlanSubscription).all()
    entitlements = get_user_entitlements(db_session, beta_result.user_id)
    assert free_result.plan_code == "FREE"
    assert beta_result.plan_code == "BETA_TESTER"
    assert len(subscriptions) == 2
    assert entitlements.plan_code == "BETA_TESTER"
    assert entitlements.allow_parameter_sweeps is True


def test_provision_user_script_accepts_beta_tester_plan_code(
    db_session,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(seed_plans, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(provision_user_script, "SessionLocal", lambda: db_session)
    seed_plans.seed()

    exit_code = provision_user_script.main(
        [
            "--email",
            "founder@example.com",
            "--display-name",
            "Founder User",
            "--plan-code",
            "BETA_TESTER",
            "--external-provider",
            "auth0",
            "--external-subject",
            "google-oauth2|112608715746802455074",
        ]
    )

    captured = capsys.readouterr()
    subscription = db_session.query(UserPlanSubscription).one()
    assert exit_code == 0
    assert "plan_code=BETA_TESTER" in captured.out
    assert subscription.plan.code == "BETA_TESTER"
