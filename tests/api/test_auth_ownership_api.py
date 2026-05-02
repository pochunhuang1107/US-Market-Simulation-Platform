from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from market_simulator import settings as settings_module
from market_simulator.db.enums import (
    ArtifactStorageType,
    ExecutorType,
    RunStatus,
    RunType,
    SubscriptionStatus,
    StrategyStatus,
    UserStatus,
)
from market_simulator.db.models.run import Run
from market_simulator.db.models.user import Plan, UserPlanSubscription
from market_simulator.repositories.runs import create_run, mark_run_succeeded
from market_simulator.settings import Settings


DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


def _set_auth_settings(
    monkeypatch,
    *,
    env: str,
    auth_mode: str | None,
    dev_user_id: str | None = DEV_USER_ID,
):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(env=env, auth_mode=auth_mode, dev_default_user_id=dev_user_id),
    )


def _attach_plan(db_session, *, user_id: str, code: str, daily_free_runs: int = 1000):
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=code.title(),
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=daily_free_runs,
        max_saved_strategies=1000,
        max_tracked_strategies=1000,
        builder_prompt_daily_limit=1000,
        builder_prompt_max_chars=5000,
        max_backtest_years=25,
        max_comparison_runs=4,
        allow_portfolio_runs=True,
        allow_comparison_runs=True,
        allow_parameter_sweeps=True,
        allow_ai_builder=True,
        allow_strategy_history=True,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)

    subscription = UserPlanSubscription(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=datetime.now(timezone.utc) - timedelta(days=1),
        ends_at=None,
        auto_renew=False,
    )
    db_session.add(subscription)
    db_session.commit()
    return plan


def _succeeded_run(
    db_session,
    *,
    user_id: str,
    strategy_id: str | None = None,
    version_id: str | None = None,
):
    run = create_run(
        db_session,
        user_id,
        strategy_id,
        version_id,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": str(uuid.uuid4())},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    return mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 10.0},
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"summary": f"summary-{run.id}"},
    )


def _succeeded_sweep_run(db_session, *, user_id: str, config: dict):
    run = create_run(
        db_session,
        user_id,
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"base_config": config, "grid": {"entry_rule.threshold": [20]}},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    variant_config = {**config, "entry_rule": {**config["entry_rule"], "threshold": 20}}
    return mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": "sharpe_ratio",
            "best_variant": {"variant_id": "variant-1", "config": variant_config},
            "results": [{"variant_id": "variant-1", "config": variant_config}],
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": f"sweep-{run.id}"},
    )


def _strategy_v2_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-rsi",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "QQQ",
        "reference_symbols": [],
        "start_date": "2021-01-01",
        "end_date": "2021-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 0,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 30,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 70,
        },
        "risk": {"stop_loss_pct": None, "take_profit_pct": None, "cooldown_bars": 0},
        "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
    }


def test_auth_settings_keep_dev_convenient_but_force_required_in_protected_envs():
    assert Settings(env="local", auth_mode=None).resolved_auth_mode == "dev"
    assert Settings(env="test", auth_mode=None).resolved_auth_mode == "dev"
    assert Settings(env="local", auth_mode=None).is_dev_auth_enabled is True

    production_settings = Settings(env="production", auth_mode="dev")
    assert production_settings.resolved_auth_mode == "required"
    assert production_settings.is_dev_auth_enabled is False

    beta_settings = Settings(env="beta", auth_mode="dev")
    assert beta_settings.resolved_auth_mode == "required"
    assert beta_settings.is_dev_auth_enabled is False


def test_dev_mode_default_user_fallback_still_works(real_auth_client, create_user, monkeypatch):
    _set_auth_settings(monkeypatch, env="local", auth_mode=None)
    create_user(user_id=DEV_USER_ID, email="dev-default@example.com")

    response = real_auth_client.get("/me/entitlements")

    assert response.status_code == 200
    assert response.json()["user"]["id"] == DEV_USER_ID


def test_x_user_id_works_only_when_dev_auth_is_enabled(
    real_auth_client,
    create_user,
    monkeypatch,
):
    user_id = str(uuid.uuid4())
    create_user(user_id=user_id, email="header-user@example.com")

    _set_auth_settings(monkeypatch, env="local", auth_mode="dev")
    dev_response = real_auth_client.get("/me/entitlements", headers={"X-User-Id": user_id})
    assert dev_response.status_code == 200
    assert dev_response.json()["user"]["id"] == user_id

    _set_auth_settings(monkeypatch, env="local", auth_mode="required")
    required_response = real_auth_client.get("/me/entitlements", headers={"X-User-Id": user_id})
    assert required_response.status_code == 401
    assert required_response.json()["detail"] == "Missing authenticated user"

    _set_auth_settings(monkeypatch, env="beta", auth_mode="dev")
    beta_response = real_auth_client.get("/me/entitlements", headers={"X-User-Id": user_id})
    assert beta_response.status_code == 401
    assert beta_response.json()["detail"] == "Missing authenticated user"


def test_production_beta_mode_rejects_unauthenticated_and_x_user_id_only(
    real_auth_client,
    create_user,
    monkeypatch,
):
    user_id = str(uuid.uuid4())
    create_user(user_id=user_id, email="beta-user@example.com")
    _set_auth_settings(monkeypatch, env="beta", auth_mode="required")

    assert real_auth_client.get("/me/entitlements").status_code == 401
    assert (
        real_auth_client.get("/me/entitlements", headers={"X-User-Id": user_id}).status_code
        == 401
    )

    _set_auth_settings(monkeypatch, env="production", auth_mode="dev")
    production_response = real_auth_client.get(
        "/me/entitlements",
        headers={"X-User-Id": user_id},
    )
    assert production_response.status_code == 401
    assert production_response.json()["detail"] == "Missing authenticated user"


def test_current_user_rejects_invalid_x_user_id(real_auth_client, monkeypatch):
    _set_auth_settings(monkeypatch, env="local", auth_mode="dev")

    response = real_auth_client.get("/me/entitlements", headers={"X-User-Id": "not-a-uuid"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid user id"


def test_current_user_rejects_missing_user(real_auth_client, monkeypatch):
    _set_auth_settings(monkeypatch, env="local", auth_mode="dev")
    missing_user_id = str(uuid.uuid4())

    response = real_auth_client.get("/me/entitlements", headers={"X-User-Id": missing_user_id})

    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"


def test_current_user_requires_active_user(real_auth_client, db_session, create_user, monkeypatch):
    user_id = str(uuid.uuid4())
    user = create_user(user_id=user_id, email="inactive-user@example.com")
    user.status = UserStatus.SUSPENDED
    db_session.commit()
    _set_auth_settings(monkeypatch, env="local", auth_mode="dev")

    response = real_auth_client.get("/me/entitlements", headers={"X-User-Id": user_id})

    assert response.status_code == 403
    assert response.json()["detail"] == "User is not active"


def test_owner_can_access_owned_strategy_run_dashboard_compare_and_sweep_detail(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="owner-access@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_1 = _succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        version_id=str(version.id),
    )
    run_2 = _succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        version_id=str(version.id),
    )
    sweep_run = _succeeded_sweep_run(
        db_session,
        user_id=current_user_ctx["id"],
        config=_strategy_v2_config(),
    )

    def fake_load_chart_data(_manifest):
        return {
            "equity_curve": [
                {
                    "date": "2021-01-01",
                    "strategy_equity": 100000.0,
                    "benchmark_equity": 100000.0,
                }
            ],
            "drawdown_curve": [],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.chart_service.load_chart_data",
        fake_load_chart_data,
    )
    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    assert client.get(f"/strategies/{strategy.id}/dashboard").status_code == 200
    assert client.get(f"/runs/{run_1.id}/dashboard").status_code == 200
    assert client.get(f"/runs/compare?run_ids={run_1.id},{run_2.id}").status_code == 200
    assert client.get(f"/runs/{sweep_run.id}/sweep/variants/variant-1").status_code == 200


def test_strategy_apis_scope_list_and_deny_non_owner_mutations(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="strategy-owner@example.com")
    create_user(user_id=other_id, email="strategy-other@example.com")
    owner_strategy, _ = create_strategy_bundle(
        user_id=owner_id,
        strategy_name="Owner Strategy",
        config_json=_strategy_v2_config(),
    )
    other_strategy, _ = create_strategy_bundle(
        user_id=other_id,
        strategy_name="Other Strategy",
        config_json=_strategy_v2_config(),
    )

    current_user_ctx["id"] = other_id

    list_response = client.get("/strategies?include_archived=true")
    assert list_response.status_code == 200
    assert {item["id"] for item in list_response.json()} == {str(other_strategy.id)}

    assert client.get(f"/strategies/{owner_strategy.id}/dashboard").status_code == 404

    version_response = client.post(
        f"/strategies/{owner_strategy.id}/versions",
        json={
            "config": _strategy_v2_config(),
            "change_note": "should not cross ownership boundary",
        },
    )
    assert version_response.status_code == 404
    assert version_response.json()["detail"] == "Strategy not found"

    archive_response = client.post(f"/strategies/{owner_strategy.id}/archive")
    assert archive_response.status_code == 404
    assert archive_response.json()["detail"] == "Strategy not found"
    db_session.refresh(owner_strategy)
    assert owner_strategy.status == StrategyStatus.ACTIVE

    owner_strategy.status = StrategyStatus.ARCHIVED
    db_session.commit()
    restore_response = client.post(f"/strategies/{owner_strategy.id}/restore")
    assert restore_response.status_code == 404
    assert restore_response.json()["detail"] == "Strategy not found"
    db_session.refresh(owner_strategy)
    assert owner_strategy.status == StrategyStatus.ARCHIVED


def test_run_apis_scope_lists_and_deny_non_owner_details_charts_and_actions(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="run-owner@example.com")
    create_user(user_id=other_id, email="run-other@example.com")
    owner_strategy, owner_version = create_strategy_bundle(user_id=owner_id)
    other_strategy, other_version = create_strategy_bundle(user_id=other_id)
    owner_run = _succeeded_run(
        db_session,
        user_id=owner_id,
        strategy_id=str(owner_strategy.id),
        version_id=str(owner_version.id),
    )
    owner_pending_run = create_run(
        db_session,
        owner_id,
        str(owner_strategy.id),
        str(owner_version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "owner pending action target"},
        max_attempts=3,
    )
    other_run = _succeeded_run(
        db_session,
        user_id=other_id,
        strategy_id=str(other_strategy.id),
        version_id=str(other_version.id),
    )

    current_user_ctx["id"] = other_id

    list_response = client.get("/runs")
    assert list_response.status_code == 200
    assert {item["id"] for item in list_response.json()["items"]} == {str(other_run.id)}

    dashboard_list_response = client.get("/runs/dashboard")
    assert dashboard_list_response.status_code == 200
    assert {item["run_id"] for item in dashboard_list_response.json()["items"]} == {
        str(other_run.id)
    }

    assert client.get(f"/runs/{owner_run.id}").status_code == 404
    assert client.get(f"/runs/{owner_run.id}/dashboard").status_code == 404
    assert client.get(f"/runs/{owner_run.id}/chart-data").status_code == 404
    assert client.post(f"/runs/{owner_pending_run.id}/enqueue").status_code == 404
    assert client.post(f"/runs/{owner_pending_run.id}/cancel").status_code == 404


def test_non_owner_cannot_access_user_scoped_run_and_sweep_surfaces(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="owner-scoped@example.com")
    create_user(user_id=other_id, email="other-scoped@example.com")
    strategy, version = create_strategy_bundle(user_id=owner_id)
    run = _succeeded_run(
        db_session,
        user_id=owner_id,
        strategy_id=str(strategy.id),
        version_id=str(version.id),
    )
    sweep_run = _succeeded_sweep_run(db_session, user_id=owner_id, config=_strategy_v2_config())

    current_user_ctx["id"] = other_id

    assert client.get(f"/strategies/{strategy.id}/dashboard").status_code == 404
    assert client.get(f"/runs/{run.id}").status_code == 404
    assert client.get(f"/runs/{run.id}/dashboard").status_code == 404
    assert client.get(f"/runs/{run.id}/chart-data").status_code == 404
    assert client.get(f"/runs/{run.id}/sleeve-chart").status_code == 404
    assert client.get(f"/runs/{sweep_run.id}/sweep/variants/variant-1").status_code == 404


def test_save_draft_run_as_strategy_cannot_save_another_users_run(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="draft-owner@example.com")
    create_user(user_id=other_id, email="draft-other@example.com")
    run = Run(
        id=uuid.uuid4(),
        user_id=owner_id,
        strategy_id=None,
        strategy_version_id=None,
        run_type=RunType.SIMULATION,
        executor_type=ExecutorType.SIMULATION_EXECUTOR,
        status=RunStatus.SUCCEEDED,
        request_payload={"draft_config": _strategy_v2_config()},
        summary_json={"total_return_pct": 10.0},
        artifact_manifest_json={"summary": "summary"},
        artifact_dir="data/local_artifacts/runs/draft-save",
        artifact_storage_type=ArtifactStorageType.LOCAL,
        attempt_count=1,
        max_attempts=3,
        progress_pct=100,
        progress_message="Run completed",
    )
    db_session.add(run)
    db_session.commit()

    current_user_ctx["id"] = other_id
    response = client.post(f"/runs/{run.id}/save-strategy", json={"name": "Should fail"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_promote_sweep_variant_cannot_promote_another_users_sweep_run(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="promote-owner@example.com")
    create_user(user_id=other_id, email="promote-other@example.com")
    sweep_run = _succeeded_sweep_run(db_session, user_id=owner_id, config=_strategy_v2_config())

    current_user_ctx["id"] = other_id
    response = client.post(f"/runs/{sweep_run.id}/sweep/variants/variant-1/promote", json={})

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_compare_fails_if_any_compared_run_is_not_owned_by_current_user(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="compare-owner@example.com")
    create_user(user_id=other_id, email="compare-other@example.com")
    own_run = _succeeded_run(db_session, user_id=other_id)
    foreign_run = _succeeded_run(db_session, user_id=owner_id)

    current_user_ctx["id"] = other_id
    response = client.get(f"/runs/compare?run_ids={own_run.id},{foreign_run.id}")

    assert response.status_code == 404
    assert "Run not found" in response.json()["detail"]


def test_compare_chart_fails_if_any_compared_run_is_not_owned_by_current_user(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="compare-chart-owner@example.com")
    create_user(user_id=other_id, email="compare-chart-other@example.com")
    own_run = _succeeded_run(db_session, user_id=other_id)
    foreign_run = _succeeded_run(db_session, user_id=owner_id)

    current_user_ctx["id"] = other_id
    response = client.get(f"/runs/compare/chart?run_ids={own_run.id},{foreign_run.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"Run not found: {foreign_run.id}"


def test_compare_sweep_variant_fails_for_non_owner(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="compare-sweep-owner@example.com")
    create_user(user_id=other_id, email="compare-sweep-other@example.com")
    own_run = _succeeded_run(db_session, user_id=other_id)
    sweep_run = _succeeded_sweep_run(db_session, user_id=owner_id, config=_strategy_v2_config())

    current_user_ctx["id"] = other_id
    response = client.get(
        f"/runs/compare?results=run:{own_run.id},sweep_variant:{sweep_run.id}:variant-1"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == f"Sweep run not found: {sweep_run.id}"


def test_compare_chart_sweep_variant_fails_for_non_owner(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="compare-chart-sweep-owner@example.com")
    create_user(user_id=other_id, email="compare-chart-sweep-other@example.com")
    own_run = _succeeded_run(db_session, user_id=other_id)
    sweep_run = _succeeded_sweep_run(db_session, user_id=owner_id, config=_strategy_v2_config())

    current_user_ctx["id"] = other_id
    response = client.get(
        f"/runs/compare/chart?results=run:{own_run.id},sweep_variant:{sweep_run.id}:variant-1"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == f"Sweep run not found: {sweep_run.id}"


def test_tracking_create_cannot_track_another_users_strategy(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    create_user(user_id=owner_id, email="tracking-owner@example.com")
    create_user(user_id=other_id, email="tracking-other@example.com")
    strategy, version = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = other_id
    response = client.post(
        "/tracked-strategies",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "tracking_mode": "PINNED_VERSION",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"


def test_entitlements_are_scoped_to_current_user(client, db_session, create_user, current_user_ctx):
    user_a = create_user(
        user_id=str(uuid.uuid4()),
        email="plan-a@example.com",
        with_default_plan=False,
    )
    user_b = create_user(
        user_id=str(uuid.uuid4()),
        email="plan-b@example.com",
        with_default_plan=False,
    )
    _attach_plan(db_session, user_id=str(user_a.id), code="PLAN_A", daily_free_runs=3)
    _attach_plan(db_session, user_id=str(user_b.id), code="PLAN_B", daily_free_runs=9)

    current_user_ctx["id"] = str(user_a.id)
    response_a = client.get("/me/entitlements")
    assert response_a.status_code == 200
    assert response_a.json()["plan"]["code"] == "PLAN_A"
    assert response_a.json()["limits"]["daily_free_runs"] == 3

    current_user_ctx["id"] = str(user_b.id)
    response_b = client.get("/me/entitlements")
    assert response_b.status_code == 200
    assert response_b.json()["plan"]["code"] == "PLAN_B"
    assert response_b.json()["limits"]["daily_free_runs"] == 9
