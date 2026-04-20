from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from market_simulator.db.enums import SubscriptionStatus
from market_simulator.db.models.builder_prompt_event import BuilderPromptEvent
from market_simulator.db.models.user import Plan, UserPlanSubscription


@pytest.fixture(autouse=True)
def default_builder_guardrail_user(create_user, current_user_ctx):
    create_user(
        user_id=current_user_ctx["id"],
        email="builder-guardrail@example.com",
        with_default_plan=False,
    )


def create_plan(
    db_session,
    *,
    code: str,
    builder_prompt_daily_limit: int,
    builder_prompt_max_chars: int,
    max_backtest_years: int,
):
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=code.title(),
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=5,
        max_saved_strategies=5,
        max_tracked_strategies=0,
        builder_prompt_daily_limit=builder_prompt_daily_limit,
        builder_prompt_max_chars=builder_prompt_max_chars,
        max_backtest_years=max_backtest_years,
        allow_portfolio_runs=False,
        allow_comparison_runs=False,
        allow_parameter_sweeps=False,
        allow_ai_builder=True,
        allow_strategy_history=False,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def attach_plan(db_session, *, user_id: str, plan_id):
    subscription = UserPlanSubscription(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_id=plan_id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=datetime.now(timezone.utc) - timedelta(days=1),
        ends_at=None,
        auto_renew=False,
    )
    db_session.add(subscription)
    db_session.commit()
    db_session.refresh(subscription)
    return subscription


def test_builder_rejects_prompt_over_plan_char_limit(client, db_session, current_user_ctx):
    plan = create_plan(
        db_session,
        code="FREE",
        builder_prompt_daily_limit=20,
        builder_prompt_max_chars=25,
        max_backtest_years=5,
    )
    attach_plan(db_session, user_id=current_user_ctx["id"], plan_id=plan.id)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a QQQ RSI strategy with a stop loss and benchmark SPY"},
    )

    assert response.status_code == 400
    assert "Prompt exceeds your plan limit" in response.json()["detail"]


def test_builder_rejects_when_daily_prompt_limit_reached(client, db_session, current_user_ctx):
    plan = create_plan(
        db_session,
        code="FREE",
        builder_prompt_daily_limit=1,
        builder_prompt_max_chars=1000,
        max_backtest_years=5,
    )
    attach_plan(db_session, user_id=current_user_ctx["id"], plan_id=plan.id)

    first = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a QQQ strategy from 2020-01-02 to 2024-12-31 with 10% stop loss"
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Adjust RSI entry to 25"},
    )
    assert second.status_code == 403
    assert "Daily builder prompt limit reached" in second.json()["detail"]


def test_builder_rejects_unsupported_symbol_for_current_data_coverage(
    client,
    db_session,
    current_user_ctx,
):
    plan = create_plan(
        db_session,
        code="FREE",
        builder_prompt_daily_limit=20,
        builder_prompt_max_chars=1000,
        max_backtest_years=5,
    )
    attach_plan(db_session, user_id=current_user_ctx["id"], plan_id=plan.id)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for AAPL from 2020-01-02 to 2024-12-31 using SPY as benchmark"
        },
    )

    assert response.status_code == 400
    assert "not supported yet" in response.json()["detail"]
    assert "ETF-first" in response.json()["detail"]


def test_builder_rejects_backtest_window_over_plan_limit(client, db_session, current_user_ctx):
    plan = create_plan(
        db_session,
        code="FREE",
        builder_prompt_daily_limit=20,
        builder_prompt_max_chars=1000,
        max_backtest_years=3,
    )
    attach_plan(db_session, user_id=current_user_ctx["id"], plan_id=plan.id)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a QQQ strategy from 2019-01-02 to 2024-12-31 with 10% stop loss"
        },
    )

    assert response.status_code == 400
    assert "current plan limit" in response.json()["detail"]
    assert "shorten the range" in response.json()["detail"]


def test_builder_records_prompt_events_for_accepted_and_rejected_requests(
    client,
    db_session,
    current_user_ctx,
):
    plan = create_plan(
        db_session,
        code="FREE",
        builder_prompt_daily_limit=20,
        builder_prompt_max_chars=1000,
        max_backtest_years=5,
    )
    attach_plan(db_session, user_id=current_user_ctx["id"], plan_id=plan.id)

    accepted = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a QQQ strategy from 2020-01-02 to 2024-12-31 with 10% stop loss"
        },
    )
    rejected = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a strategy for AAPL from 2020-01-02 to 2024-12-31"
        },
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 400

    events = db_session.query(BuilderPromptEvent).all()
    statuses = sorted(event.status for event in events)

    assert statuses == ["ACCEPTED", "REJECTED"]