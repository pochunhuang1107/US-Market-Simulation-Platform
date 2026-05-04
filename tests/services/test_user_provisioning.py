from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from market_simulator.db.enums import SubscriptionStatus, UserStatus
from market_simulator.db.models.user import Plan, User, UserPlanSubscription
from market_simulator.services.user_provisioning import ProvisioningError, provision_user


def _create_free_plan(db_session) -> Plan:
    plan = Plan(
        id=uuid.uuid4(),
        code="FREE",
        name="Free",
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=5,
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
    db_session.commit()
    return plan


def test_provision_user_creates_new_user(db_session):
    _create_free_plan(db_session)

    result = provision_user(
        db_session,
        email="beta@example.com",
        display_name="Beta User",
        plan_code="FREE",
    )

    user = db_session.query(User).filter(User.email == "beta@example.com").one()
    assert result.user_action == "created"
    assert result.plan_action == "assigned"
    assert user.display_name == "Beta User"
    assert user.status == UserStatus.ACTIVE


def test_provision_user_is_idempotent(db_session):
    _create_free_plan(db_session)

    first = provision_user(db_session, email="beta@example.com", plan_code="FREE")
    second = provision_user(db_session, email="beta@example.com", plan_code="FREE")

    assert first.user_action == "created"
    assert second.user_action == "existing"
    assert second.plan_action == "existing"
    assert db_session.query(User).count() == 1
    assert db_session.query(UserPlanSubscription).count() == 1


def test_provision_user_assigns_free_plan(db_session):
    plan = _create_free_plan(db_session)

    provision_user(db_session, email="beta@example.com", plan_code="FREE", provider="oidc")

    subscription = db_session.query(UserPlanSubscription).one()
    assert subscription.plan_id == plan.id
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.provider == "oidc"
    assert subscription.ends_at is None


def test_provision_user_updates_display_name_when_requested(db_session):
    _create_free_plan(db_session)

    provision_user(db_session, email="beta@example.com", display_name="Old Name", plan_code="FREE")
    result = provision_user(
        db_session,
        email="beta@example.com",
        display_name="New Name",
        update_display_name=True,
        plan_code="FREE",
    )

    user = db_session.query(User).filter(User.email == "beta@example.com").one()
    assert result.user_action == "updated"
    assert user.display_name == "New Name"


def test_provision_user_rejects_unknown_plan(db_session):
    with pytest.raises(ProvisioningError, match="Unknown plan code: MISSING"):
        provision_user(db_session, email="beta@example.com", plan_code="MISSING")

    assert db_session.query(User).count() == 0
    assert db_session.query(UserPlanSubscription).count() == 0


def test_provision_user_normalizes_email_for_matching(db_session):
    _create_free_plan(db_session)

    first = provision_user(db_session, email="Beta.User@Example.COM ", plan_code="free")
    second = provision_user(db_session, email=" beta.user@example.com", plan_code="FREE")

    user = db_session.query(User).one()
    assert first.email == "beta.user@example.com"
    assert second.user_action == "existing"
    assert user.email == "beta.user@example.com"
    assert db_session.query(UserPlanSubscription).count() == 1


def test_provision_user_deactivates_only_when_status_update_requested(db_session):
    _create_free_plan(db_session)

    provision_user(db_session, email="beta@example.com", plan_code="FREE")
    provision_user(
        db_session,
        email="beta@example.com",
        status="SUSPENDED",
        update_status=True,
        plan_code="FREE",
    )
    provision_user(db_session, email="beta@example.com", plan_code="FREE")

    user = db_session.query(User).filter(User.email == "beta@example.com").one()
    assert user.status == UserStatus.SUSPENDED


def test_provision_user_dry_run_rolls_back_changes(db_session):
    _create_free_plan(db_session)

    result = provision_user(db_session, email="beta@example.com", plan_code="FREE", dry_run=True)

    assert result.dry_run is True
    assert result.user_action == "created"
    assert result.plan_action == "assigned"
    assert db_session.query(User).count() == 0
    assert db_session.query(UserPlanSubscription).count() == 0
