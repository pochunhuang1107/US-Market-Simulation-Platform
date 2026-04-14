from __future__ import annotations

import uuid

from market_simulator.db.enums import (
    ArtifactStorageType,
    ExecutorType,
    RunStatus,
    RunType,
    StrategyStatus,
    StrategyType,
)
from market_simulator.db.models.run import Run
from market_simulator.db.models.strategy import Strategy


def test_get_me_entitlements_returns_plan_features_and_usage(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="me@example.com",
        display_name="Me User",
    )

    strategy = Strategy(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Saved Strategy",
        description="Saved strategy",
        strategy_type=StrategyType.SIMULATION,
        visibility="PRIVATE",
        status=StrategyStatus.ACTIVE,
    )
    db_session.add(strategy)

    run = Run(
        id=uuid.uuid4(),
        user_id=user.id,
        strategy_id=strategy.id,
        strategy_version_id=None,
        run_type=RunType.SIMULATION,
        executor_type=ExecutorType.SIMULATION_EXECUTOR,
        status=RunStatus.PENDING,
        request_payload={"source": "test"},
        attempt_count=0,
        max_attempts=3,
        progress_pct=0,
        progress_message="Run created",
        artifact_storage_type=ArtifactStorageType.LOCAL,
    )
    db_session.add(run)
    db_session.commit()

    response = client.get("/me/entitlements")

    assert response.status_code == 200

    data = response.json()

    assert data["user"]["id"] == current_user_ctx["id"]
    assert data["user"]["email"] == "me@example.com"
    assert data["plan"]["code"] == "TEST_PRO"

    assert data["features"]["allow_ai_builder"] is True
    assert data["features"]["allow_strategy_history"] is True
    assert data["features"]["allow_portfolio_runs"] is True
    assert data["features"]["allow_comparison_runs"] is True
    assert data["features"]["allow_parameter_sweeps"] is True

    assert data["limits"]["daily_free_runs"] == 1000
    assert data["limits"]["max_saved_strategies"] == 1000
    assert data["limits"]["max_tracked_strategies"] == 1000

    assert data["usage"]["runs_created_today"] == 1
    assert data["usage"]["daily_runs_remaining"] == 999
    assert data["usage"]["saved_strategies"] == 1
    assert data["usage"]["saved_strategies_remaining"] == 999


def test_get_me_entitlements_requires_active_subscription(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="no-plan@example.com",
        with_default_plan=False,
    )

    response = client.get("/me/entitlements")

    assert response.status_code == 403
    assert response.json()["detail"] == "No active subscription plan found"