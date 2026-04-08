from __future__ import annotations

import uuid

from market_simulator.db.enums import RunStatus
from market_simulator.repositories.runs import create_run, mark_run_succeeded
from market_simulator.repositories.strategies import create_strategy_version


def test_get_strategy_dashboard_returns_strategy_versions_runs_and_latest_performance(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version_1 = create_strategy_bundle(user_id=current_user_ctx["id"])

    version_2 = create_strategy_version(
        db_session,
        strategy.id,
        {
            "name": "updated-strategy",
            "symbol": "QQQ",
            "benchmark": "QQQ",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        "hash-v2",
        uuid.UUID(current_user_ctx["id"]),
    )

    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version_2.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "dashboard test"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "total_return_pct": 42.5,
            "benchmark_return_pct": 30.1,
            "alpha_vs_benchmark_pct": 12.4,
            "cagr_pct": 7.8,
            "sharpe_ratio": 1.12,
            "max_drawdown_pct": -9.5,
            "benchmark_max_drawdown_pct": -14.0,
            "trade_count": 8,
            "win_rate_pct": 62.5,
        },
        artifact_dir="data/local_artifacts/runs/test-strategy-dashboard",
        artifact_manifest_json={
            "summary": "data/local_artifacts/runs/test-strategy-dashboard/summary.json",
        },
    )

    response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert response.status_code == 200

    body = response.json()

    assert body["strategy"]["id"] == str(strategy.id)
    assert body["strategy"]["current_version_id"] == str(version_2.id)

    assert len(body["versions"]) == 2
    assert body["versions"][0]["id"] == str(version_2.id)
    assert body["versions"][0]["is_current"] is True
    assert body["versions"][1]["id"] == str(version_1.id)
    assert body["versions"][1]["is_current"] is False

    assert body["total_runs"] == 1
    assert len(body["associated_runs"]) == 1
    assert body["associated_runs"][0]["run_id"] == str(run.id)
    assert body["associated_runs"][0]["status"] == "SUCCEEDED"
    assert body["associated_runs"][0]["total_return_pct"] == 42.5
    assert body["associated_runs"][0]["strategy_name"] == strategy.name
    assert body["associated_runs"][0]["strategy_version_number"] == version_2.version_number

    assert body["latest_run_id"] == str(run.id)
    assert body["latest_finished_at"] is not None
    assert body["latest_performance"]["run_id"] == str(run.id)
    assert body["latest_performance"]["total_return_pct"] == 42.5
    assert body["latest_performance"]["benchmark_return_pct"] == 30.1
    assert body["latest_performance"]["alpha_vs_benchmark_pct"] == 12.4
    assert body["latest_performance"]["trade_count"] == 8


def test_get_strategy_dashboard_returns_null_latest_performance_when_no_succeeded_runs(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, _ = create_strategy_bundle(user_id=current_user_ctx["id"])

    response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert response.status_code == 200

    body = response.json()
    assert body["strategy"]["id"] == str(strategy.id)
    assert body["total_runs"] == 0
    assert body["associated_runs"] == []
    assert body["latest_run_id"] is None
    assert body["latest_finished_at"] is None
    assert body["latest_performance"] is None


def test_get_strategy_dashboard_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, _ = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = other_user_id
    response = client.get(f"/strategies/{strategy.id}/dashboard")

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"


def test_create_strategy_version_api_creates_new_version_and_updates_current_version(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version_1 = create_strategy_bundle(user_id=current_user_ctx["id"])

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": {
                "name": "qqq-rsi-v2",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "start_date": "2018-01-02",
                "end_date": "2024-12-31",
                "initial_capital": 100000,
            },
            "change_note": "Adjusted entry thresholds",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["strategy_id"] == str(strategy.id)
    assert body["version_id"] != str(version_1.id)

    dashboard_response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert dashboard_response.status_code == 200

    dashboard = dashboard_response.json()
    assert dashboard["strategy"]["current_version_id"] == body["version_id"]
    assert len(dashboard["versions"]) == 2
    assert dashboard["versions"][0]["id"] == body["version_id"]
    assert dashboard["versions"][0]["version_number"] == 2
    assert dashboard["versions"][0]["change_note"] == "Adjusted entry thresholds"
    assert dashboard["versions"][0]["is_current"] is True
    assert dashboard["versions"][1]["id"] == str(version_1.id)
    assert dashboard["versions"][1]["is_current"] is False


def test_create_strategy_version_api_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, _ = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = other_user_id

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": {
                "name": "unauthorized-version",
                "tradable_symbol": "QQQ",
            },
            "change_note": "should fail",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"