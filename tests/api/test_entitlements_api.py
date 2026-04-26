from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from market_simulator.db.enums import (
    ArtifactStorageType,
    ExecutorType,
    RunStatus,
    RunType,
    StrategyStatus,
    StrategyType,
    SubscriptionStatus,
)
from market_simulator.db.models.run import Run
from market_simulator.db.models.strategy import Strategy
from market_simulator.db.models.user import Plan, UserPlanSubscription


def create_plan(
    db_session,
    *,
    code: str,
    allow_ai_builder: bool,
    allow_strategy_history: bool,
    daily_free_runs: int,
    max_saved_strategies: int,
    allow_portfolio_runs: bool = False,
    allow_comparison_runs: bool = False,
    allow_parameter_sweeps: bool = False,
    builder_prompt_daily_limit: int = 20,
    builder_prompt_max_chars: int = 1000,
    max_backtest_years: int = 5,
):
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=code.title(),
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=daily_free_runs,
        max_saved_strategies=max_saved_strategies,
        max_tracked_strategies=0,
        builder_prompt_daily_limit=builder_prompt_daily_limit,
        builder_prompt_max_chars=builder_prompt_max_chars,
        max_backtest_years=max_backtest_years,
        allow_portfolio_runs=allow_portfolio_runs,
        allow_comparison_runs=allow_comparison_runs,
        allow_parameter_sweeps=allow_parameter_sweeps,
        allow_ai_builder=allow_ai_builder,
        allow_strategy_history=allow_strategy_history,
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


def test_builder_blocked_when_plan_disables_ai_builder(client, db_session, create_user):
    user = create_user(
        user_id="00000000-0000-0000-0000-000000000001",
        with_default_plan=False,
    )
    plan = create_plan(
        db_session,
        code="FREE",
        allow_ai_builder=False,
        allow_strategy_history=False,
        daily_free_runs=5,
        max_saved_strategies=5,
    )
    attach_plan(db_session, user_id=str(user.id), plan_id=plan.id)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "RSI strategy for QQQ"},
    )

    assert response.status_code == 403
    assert "strategy builder access" in response.json()["detail"]


def test_strategy_version_blocked_when_plan_disables_history(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(
        user_id="00000000-0000-0000-0000-000000000001",
        with_default_plan=False,
    )
    plan = create_plan(
        db_session,
        code="FREE",
        allow_ai_builder=False,
        allow_strategy_history=False,
        daily_free_runs=5,
        max_saved_strategies=5,
    )
    attach_plan(db_session, user_id=str(user.id), plan_id=plan.id)

    strategy, _ = create_strategy_bundle(user_id=str(user.id))

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": {
                "name": "new-version",
                "symbol": "QQQ",
                "benchmark": "QQQ",
                "start_date": "2019-01-02",
                "end_date": "2024-12-31",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "position_sizing": {
                    "type": "percent_of_equity",
                    "value": 1.0,
                },
                "entry": {
                    "type": "rsi_below",
                    "lookback": 14,
                    "threshold": 25,
                },
                "exit": {
                    "type": "rsi_above",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {
                    "stop_loss_pct": None,
                    "take_profit_pct": None,
                },
            },
            "change_note": "tighten entry",
        },
    )

    assert response.status_code == 403
    assert "version history" in response.json()["detail"]


def test_strategy_create_blocked_when_saved_strategy_limit_reached(client, db_session, create_user):
    user = create_user(
        user_id="00000000-0000-0000-0000-000000000001",
        with_default_plan=False,
    )
    plan = create_plan(
        db_session,
        code="FREE",
        allow_ai_builder=False,
        allow_strategy_history=False,
        daily_free_runs=5,
        max_saved_strategies=1,
    )
    attach_plan(db_session, user_id=str(user.id), plan_id=plan.id)

    existing_strategy = Strategy(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Existing Strategy",
        description="already saved",
        strategy_type=StrategyType.SIMULATION,
        visibility="PRIVATE",
        status=StrategyStatus.ACTIVE,
    )
    db_session.add(existing_strategy)
    db_session.commit()

    response = client.post(
        "/strategies",
        json={
            "name": "Another Strategy",
            "description": "should fail",
            "strategy_type": "SIMULATION",
            "config": {
                "name": "another-strategy",
                "symbol": "QQQ",
                "benchmark": "QQQ",
                "start_date": "2019-01-02",
                "end_date": "2024-12-31",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "position_sizing": {"type": "percent_of_equity", "value": 1.0},
                "entry": {"type": "rsi_below", "lookback": 14, "threshold": 30},
                "exit": {"type": "rsi_above", "lookback": 14, "threshold": 70},
                "risk": {"stop_loss_pct": None, "take_profit_pct": None},
            },
        },
    )

    assert response.status_code == 403
    assert "Saved strategy limit reached" in response.json()["detail"]


def test_archived_strategies_do_not_count_toward_saved_strategy_limit(client, db_session, create_user):
    user = create_user(
        user_id="00000000-0000-0000-0000-000000000001",
        with_default_plan=False,
    )
    plan = create_plan(
        db_session,
        code="FREE",
        allow_ai_builder=False,
        allow_strategy_history=False,
        daily_free_runs=5,
        max_saved_strategies=1,
    )
    attach_plan(db_session, user_id=str(user.id), plan_id=plan.id)

    existing_strategy = Strategy(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Archived Strategy",
        description="archived saved strategy",
        strategy_type=StrategyType.SIMULATION,
        visibility="PRIVATE",
        status=StrategyStatus.ARCHIVED,
    )
    db_session.add(existing_strategy)
    db_session.commit()

    response = client.post(
        "/strategies",
        json={
            "name": "Replacement Strategy",
            "description": "should pass",
            "strategy_type": "SIMULATION",
            "config": {
                "name": "replacement-strategy",
                "symbol": "QQQ",
                "benchmark": "QQQ",
                "start_date": "2019-01-02",
                "end_date": "2024-12-31",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "position_sizing": {"type": "percent_of_equity", "value": 1.0},
                "entry": {"type": "rsi_below", "lookback": 14, "threshold": 30},
                "exit": {"type": "rsi_above", "lookback": 14, "threshold": 70},
                "risk": {"stop_loss_pct": None, "take_profit_pct": None},
            },
        },
    )

    assert response.status_code == 200


def test_run_create_blocked_when_daily_limit_reached(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(
        user_id="00000000-0000-0000-0000-000000000001",
        with_default_plan=False,
    )
    plan = create_plan(
        db_session,
        code="FREE",
        allow_ai_builder=False,
        allow_strategy_history=False,
        daily_free_runs=1,
        max_saved_strategies=5,
    )
    attach_plan(db_session, user_id=str(user.id), plan_id=plan.id)

    strategy, version = create_strategy_bundle(user_id=str(user.id))

    existing_run = Run(
        id=uuid.uuid4(),
        user_id=user.id,
        strategy_id=strategy.id,
        strategy_version_id=version.id,
        run_type=RunType.SIMULATION,
        executor_type=ExecutorType.SIMULATION_EXECUTOR,
        status=RunStatus.PENDING,
        request_payload={"foo": "bar"},
        attempt_count=0,
        max_attempts=3,
        progress_pct=0,
        progress_message="Run created",
        artifact_storage_type=ArtifactStorageType.LOCAL,
    )
    db_session.add(existing_run)
    db_session.commit()

    response = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"symbol": "QQQ"},
            "max_attempts": 3,
        },
    )

    assert response.status_code == 403
    assert "Daily run limit reached" in response.json()["detail"]
