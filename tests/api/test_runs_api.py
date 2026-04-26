from __future__ import annotations

import uuid

from market_simulator.db.enums import RunStatus
from market_simulator.db.models import Plan
from market_simulator.repositories.runs import create_run, get_run, mark_run_succeeded

def create_plan(
    db_session,
    *,
    code: str,
    builder_prompt_daily_limit: int,
    builder_prompt_max_chars: int,
    max_backtest_years: int,
):
    plan = Plan(
        code=code,
        name=code.title(),
        allow_ai_builder=True,
        allow_saved_strategies=True,
        allow_run_comparison=True,
        builder_prompt_daily_limit=builder_prompt_daily_limit,
        builder_prompt_max_chars=builder_prompt_max_chars,
        max_backtest_years=max_backtest_years,
        max_runs_per_day=50,
        max_saved_strategies=50,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def attach_plan(db_session, *, user_id: str, plan_id: str):
    existing = (
        db_session.query(UserPlanSubscription)
        .filter(
            UserPlanSubscription.user_id == user_id,
            UserPlanSubscription.is_active.is_(True),
        )
        .all()
    )
    for row in existing:
        row.is_active = False
        row.ended_at = datetime.now(timezone.utc)

    user_plan = UserPlanSubscription(
        user_id=user_id,
        plan_id=plan_id,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ended_at=None,
        is_active=True,
    )
    db_session.add(user_plan)
    db_session.commit()
    db_session.refresh(user_plan)
    return user_plan


def _create_run_via_api(
    client,
    *,
    strategy_id: str,
    strategy_version_id: str,
    run_type: str = "SIMULATION",
    executor_type: str = "SIMULATION_EXECUTOR",
    request_payload: dict | None = None,
    max_attempts: int = 3,
):
    response = client.post(
        "/runs",
        json={
            "strategy_id": strategy_id,
            "strategy_version_id": strategy_version_id,
            "run_type": run_type,
            "executor_type": executor_type,
            "request_payload": request_payload or {},
            "max_attempts": max_attempts,
        },
    )
    assert response.status_code == 200
    return response.json()


def _create_succeeded_run(
    db_session,
    *,
    user_id: str,
    strategy_id: str,
    strategy_version_id: str,
    note: str,
):
    run = create_run(
        db_session,
        user_id,
        strategy_id,
        strategy_version_id,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": note},
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
        artifact_manifest_json={"summary": f"dummy-{run.id}"},
    )


def test_create_run_returns_pending(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    response = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "api create test"},
            "max_attempts": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "PENDING"
    assert body["strategy_id"] == str(strategy.id)
    assert body["strategy_version_id"] == str(version.id)
    assert body["strategy_name"] == strategy.name
    assert body["strategy_version_number"] == version.version_number
    assert body["attempt_count"] == 0
    assert body["max_attempts"] == 3
    assert body["progress_message"] == "Run created"


def test_list_runs_returns_paginated_wrapper(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    _create_run_via_api(
        client,
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        request_payload={"note": "list test"},
    )

    response = client.get("/runs")
    assert response.status_code == 200

    body = response.json()
    assert "items" in body
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["has_next"] is False
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "PENDING"
    assert body["items"][0]["strategy_name"] == strategy.name
    assert body["items"][0]["strategy_version_number"] == version.version_number


def test_list_runs_supports_pagination(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    for i in range(3):
        _create_run_via_api(
            client,
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            request_payload={"index": i},
        )

    page_1 = client.get("/runs?page=1&page_size=2")
    assert page_1.status_code == 200
    body_1 = page_1.json()

    assert body_1["total"] == 3
    assert body_1["page"] == 1
    assert body_1["page_size"] == 2
    assert body_1["has_next"] is True
    assert len(body_1["items"]) == 2

    page_2 = client.get("/runs?page=2&page_size=2")
    assert page_2.status_code == 200
    body_2 = page_2.json()

    assert body_2["total"] == 3
    assert body_2["page"] == 2
    assert body_2["page_size"] == 2
    assert body_2["has_next"] is False
    assert len(body_2["items"]) == 1


def test_list_runs_filters_by_status(
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
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    pending_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "pending run"},
        max_attempts=3,
    )

    succeeded_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "succeeded run"},
        max_attempts=3,
    )
    succeeded_run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(succeeded_run)

    mark_run_succeeded(
        db_session,
        succeeded_run,
        summary_json={"ok": True},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-run/summary.json"},
    )

    response = client.get("/runs?status=SUCCEEDED")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(succeeded_run.id)
    assert body["items"][0]["status"] == "SUCCEEDED"
    assert body["items"][0]["id"] != str(pending_run.id)


def test_list_runs_filters_by_strategy_id(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    strategy_a, version_a = create_strategy_bundle(user_id=current_user_ctx["id"])
    strategy_b, version_b = create_strategy_bundle(user_id=current_user_ctx["id"])

    _create_run_via_api(
        client,
        strategy_id=str(strategy_a.id),
        strategy_version_id=str(version_a.id),
        request_payload={"strategy": "a"},
    )
    _create_run_via_api(
        client,
        strategy_id=str(strategy_b.id),
        strategy_version_id=str(version_b.id),
        request_payload={"strategy": "b"},
    )

    response = client.get(f"/runs?strategy_id={strategy_a.id}")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["strategy_id"] == str(strategy_a.id)


def test_list_runs_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, version = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = owner_id
    _create_run_via_api(
        client,
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        request_payload={"note": "owner run"},
    )

    current_user_ctx["id"] = other_user_id
    response = client.get("/runs")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 0
    assert body["items"] == []
    assert body["has_next"] is False


def test_list_runs_rejects_invalid_pagination(
    client,
):
    response = client.get("/runs?page=0&page_size=101")
    assert response.status_code == 422


def test_enqueue_then_cancel_run(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "enqueue cancel test"},
            "max_attempts": 3,
        },
    )
    run_id = create_resp.json()["id"]

    enqueue_resp = client.post(f"/runs/{run_id}/enqueue")
    assert enqueue_resp.status_code == 200
    assert enqueue_resp.json()["status"] == "QUEUED"

    cancel_resp = client.post(f"/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELED"

    get_resp = client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "CANCELED"
    assert get_resp.json()["progress_message"] == "Run canceled by user request"


def test_cannot_enqueue_canceled_run(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "guardrail test"},
            "max_attempts": 3,
        },
    )
    run_id = create_resp.json()["id"]

    assert client.post(f"/runs/{run_id}/cancel").status_code == 200

    enqueue_resp = client.post(f"/runs/{run_id}/enqueue")
    assert enqueue_resp.status_code == 400
    assert "cannot be enqueued" in enqueue_resp.json()["detail"].lower()


def test_cannot_cancel_succeeded_run(
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
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "succeeded run"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"ok": True},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-run/summary.json"},
    )

    cancel_resp = client.post(f"/runs/{run.id}/cancel")
    assert cancel_resp.status_code == 400
    assert "cannot be canceled" in cancel_resp.json()["detail"].lower()


def test_get_run_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, version = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = owner_id
    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "ownership test"},
            "max_attempts": 3,
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    current_user_ctx["id"] = other_user_id
    get_resp = client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 404

    enqueue_resp = client.post(f"/runs/{run_id}/enqueue")
    assert enqueue_resp.status_code == 400
    assert "not found" in enqueue_resp.json()["detail"].lower()


def test_compare_runs_chart_returns_normalized_strategy_benchmark_and_drawdown_curves(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    run_1 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "compare chart 1"},
        max_attempts=3,
    )
    run_1.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run_1)

    mark_run_succeeded(
        db_session,
        run_1,
        summary_json={"total_return_pct": 10.0},
        artifact_dir="data/local_artifacts/runs/test-compare-1",
        artifact_manifest_json={"summary": "dummy-1"},
    )

    run_2 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "compare chart 2"},
        max_attempts=3,
    )
    run_2.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run_2)

    mark_run_succeeded(
        db_session,
        run_2,
        summary_json={"total_return_pct": 20.0},
        artifact_dir="data/local_artifacts/runs/test-compare-2",
        artifact_manifest_json={"summary": "dummy-2"},
    )

    def fake_load_chart_data(manifest):
        summary_ref = manifest["summary"]

        if summary_ref == "dummy-1":
            return {
                "equity_curve": [
                    {"date": "2024-01-01", "strategy_equity": 100000.0, "benchmark_equity": 100000.0},
                    {"date": "2024-01-02", "strategy_equity": 110000.0, "benchmark_equity": 105000.0},
                ],
                "drawdown_curve": [
                    {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                    {"date": "2024-01-02", "strategy_drawdown_pct": -2.0, "benchmark_drawdown_pct": -1.0},
                ],
                "monthly_returns": [],
                "sleeve_equity_curve": [],
                "sleeve_weight_curve": [],
                "trade_markers": [],
            }

        return {
            "equity_curve": [
                {"date": "2024-01-01", "strategy_equity": 200000.0, "benchmark_equity": 200000.0},
                {"date": "2024-01-02", "strategy_equity": 220000.0, "benchmark_equity": 210000.0},
            ],
            "drawdown_curve": [
                {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-01-02", "strategy_drawdown_pct": -3.0, "benchmark_drawdown_pct": -1.5},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    response = client.get(f"/runs/compare/chart?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()

    assert "strategy_curves" in body
    assert "benchmark_curves" in body
    assert "strategy_drawdown_curves" in body
    assert "benchmark_drawdown_curves" in body

    assert len(body["strategy_curves"]) == 2
    assert len(body["benchmark_curves"]) == 2
    assert len(body["strategy_drawdown_curves"]) == 2
    assert len(body["benchmark_drawdown_curves"]) == 2

    assert body["strategy_curves"][0]["label"] is not None
    assert body["benchmark_curves"][0]["label"] is not None
    assert body["strategy_drawdown_curves"][0]["label"] is not None
    assert body["benchmark_drawdown_curves"][0]["label"] is not None

    assert body["strategy_curves"][0]["points"][0]["value"] == 100.0
    assert body["strategy_curves"][0]["points"][1]["value"] == 110.0
    assert body["benchmark_curves"][0]["points"][0]["value"] == 100.0
    assert body["benchmark_curves"][0]["points"][1]["value"] == 105.0

    assert body["strategy_curves"][1]["points"][0]["value"] == 100.0
    assert body["strategy_curves"][1]["points"][1]["value"] == 110.0
    assert body["benchmark_curves"][1]["points"][0]["value"] == 100.0
    assert body["benchmark_curves"][1]["points"][1]["value"] == 105.0

    assert body["strategy_drawdown_curves"][0]["points"][1]["value"] == -2.0
    assert body["benchmark_drawdown_curves"][0]["points"][1]["value"] == -1.0
    assert body["strategy_drawdown_curves"][1]["points"][1]["value"] == -3.0
    assert body["benchmark_drawdown_curves"][1]["points"][1]["value"] == -1.5


def test_compare_runs_returns_strategy_metadata(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "compare summary metadata"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-compare-summary",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-compare-summary/summary.json"},
    )

    run_2 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "compare summary metadata 2"},
        max_attempts=3,
    )
    run_2.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run_2)

    mark_run_succeeded(
        db_session,
        run_2,
        summary_json={"total_return_pct": 15.6},
        artifact_dir="data/local_artifacts/runs/test-compare-summary-2",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-compare-summary-2/summary.json"},
    )

    response = client.get(f"/runs/compare?run_ids={run.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()
    assert len(body["runs"]) == 2

    target_run = next(item for item in body["runs"] if item["run_id"] == str(run.id))

    assert target_run["strategy_id"] == str(strategy.id)
    assert target_run["strategy_version_id"] == str(version.id)
    assert target_run["strategy_name"] == strategy.name
    assert target_run["strategy_version_number"] == version.version_number


def test_compare_runs_rejects_more_than_max_comparison_runs(
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
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    runs = [
        _create_succeeded_run(
            db_session,
            user_id=current_user_ctx["id"],
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            note=f"compare limit {index}",
        )
        for index in range(5)
    ]

    run_ids = ",".join(str(run.id) for run in runs)
    response = client.get(f"/runs/compare?run_ids={run_ids}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Comparison limit reached for your plan (max 4 runs)."


def test_compare_runs_chart_rejects_more_than_max_comparison_runs(
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
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    runs = [
        _create_succeeded_run(
            db_session,
            user_id=current_user_ctx["id"],
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            note=f"compare chart limit {index}",
        )
        for index in range(5)
    ]

    run_ids = ",".join(str(run.id) for run in runs)
    response = client.get(f"/runs/compare/chart?run_ids={run_ids}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Comparison limit reached for your plan (max 4 runs)."


def test_compare_runs_allows_exactly_max_comparison_runs(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    runs = [
        _create_succeeded_run(
            db_session,
            user_id=current_user_ctx["id"],
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            note=f"compare max {index}",
        )
        for index in range(4)
    ]

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        lambda manifest: {
            "equity_curve": [
                {"date": "2024-01-01", "strategy_equity": 100000.0, "benchmark_equity": 100000.0},
                {"date": "2024-01-02", "strategy_equity": 101000.0, "benchmark_equity": 100500.0},
            ],
            "drawdown_curve": [
                {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-01-02", "strategy_drawdown_pct": -1.0, "benchmark_drawdown_pct": -0.5},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        },
    )

    run_ids = ",".join(str(run.id) for run in runs)

    compare_response = client.get(f"/runs/compare?run_ids={run_ids}")
    assert compare_response.status_code == 200
    assert len(compare_response.json()["runs"]) == 4

    chart_response = client.get(f"/runs/compare/chart?run_ids={run_ids}")
    assert chart_response.status_code == 200
    assert len(chart_response.json()["strategy_curves"]) == 4


def test_compare_runs_requires_at_least_two_runs(client):
    response = client.get("/runs/compare?run_ids=00000000-0000-0000-0000-000000000001")

    assert response.status_code == 400
    assert "at least two run ids are required" in response.json()["detail"].lower()


def test_get_run_returns_strategy_metadata(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "get run metadata test"},
            "max_attempts": 3,
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["id"] == run_id
    assert body["strategy_id"] == str(strategy.id)
    assert body["strategy_version_id"] == str(version.id)
    assert body["strategy_name"] == strategy.name
    assert body["strategy_version_number"] == version.version_number


def test_get_run_dashboard_returns_nested_run_strategy_metadata(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "dashboard metadata"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-dashboard-metadata",
        artifact_manifest_json={"summary": "dummy"},
    )

    def fake_load_chart_data(_):
        return {
            "equity_curve": [],
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

    response = client.get(f"/runs/{run.id}/dashboard")
    assert response.status_code == 200

    body = response.json()
    assert body["run"]["id"] == str(run.id)
    assert body["run"]["strategy_id"] == str(strategy.id)
    assert body["run"]["strategy_version_id"] == str(version.id)
    assert body["run"]["strategy_name"] == strategy.name
    assert body["run"]["strategy_version_number"] == version.version_number


def test_get_run_chart_data_preserves_trade_marker_actions(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "trade marker labels"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-trade-markers",
        artifact_manifest_json={"summary": "dummy"},
    )

    def fake_load_chart_data(_):
        return {
            "equity_curve": [],
            "drawdown_curve": [],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [
                {
                    "date": "2024-01-02",
                    "side": "BUY",
                    "shares": 100.0,
                    "price": 100.0,
                    "reason": None,
                },
                {
                    "date": "2024-01-10",
                    "side": "BUY_ADD",
                    "shares": 25.0,
                    "price": 102.0,
                    "reason": None,
                },
                {
                    "date": "2024-01-15",
                    "side": "SELL_REDUCE",
                    "shares": 50.0,
                    "price": 105.0,
                    "reason": "exit_signal",
                },
                {
                    "date": "2024-01-20",
                    "side": "SELL_ALL",
                    "shares": 75.0,
                    "price": 107.0,
                    "reason": "exit_signal",
                },
            ],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    response = client.get(f"/runs/{run.id}/chart-data")
    assert response.status_code == 200

    body = response.json()
    assert body["run_id"] == str(run.id)

    markers = body["trade_markers"]
    assert [marker["side"] for marker in markers] == [
        "BUY",
        "BUY_ADD",
        "SELL_REDUCE",
        "SELL_ALL",
    ]
    assert markers[0]["shares"] == 100.0
    assert markers[1]["shares"] == 25.0
    assert markers[2]["reason"] == "exit_signal"
    assert markers[3]["price"] == 107.0


def test_compare_runs_chart_requires_at_least_two_runs(
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
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "single compare chart run"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 10.0},
        artifact_dir="data/local_artifacts/runs/test-single-compare-chart",
        artifact_manifest_json={"summary": "dummy"},
    )

    response = client.get(f"/runs/compare/chart?run_ids={run.id}")
    assert response.status_code == 400
    assert "at least two run ids are required" in response.json()["detail"].lower()


def test_runs_dashboard_supports_filter_and_sort(
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

    strategy_a, version_a = create_strategy_bundle(user_id=current_user_ctx["id"])
    strategy_b, version_b = create_strategy_bundle(user_id=current_user_ctx["id"])

    run_1 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy_a.id),
        str(version_a.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "dashboard test 1"},
        max_attempts=3,
    )
    run_1.status = RunStatus.SUCCEEDED

    run_2 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy_b.id),
        str(version_b.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "dashboard test 2"},
        max_attempts=3,
    )
    run_2.status = RunStatus.FAILED

    db_session.commit()

    response = client.get(
        f"/runs/dashboard?status=SUCCEEDED&strategy_id={strategy_a.id}&sort_by=created_at&sort_order=desc"
    )
    assert response.status_code == 200

    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1

    item = body["items"][0]

    assert item["run_id"] == str(run_1.id)
    assert item["strategy_id"] == str(strategy_a.id)
    assert item["status"] == "SUCCEEDED"


def test_runs_dashboard_invalid_pagination_returns_422(client):
    response = client.get("/runs/dashboard?page=0&page_size=101")
    assert response.status_code == 422


def test_create_draft_run_without_saved_strategy_returns_pending(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "draft-run",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
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
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "PENDING"
    assert body["strategy_id"] is None
    assert body["strategy_version_id"] is None
    assert body["strategy_name"] is None
    assert body["request_payload"]["draft_config"]["tradable_symbol"] == "QQQ"


def test_save_draft_run_as_strategy_creates_strategy_and_links_run(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    create_resp = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "draft-run",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
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
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    run = get_run(db_session, run_id)
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary_json": "summary.json"},
    )

    save_resp = client.post(
        f"/runs/{run_id}/save-strategy",
        json={
            "name": "My Saved Draft",
            "description": "Saved from run detail",
            "strategy_type": "SINGLE_ASSET",
        },
    )
    assert save_resp.status_code == 200

    body = save_resp.json()
    assert body["run_id"] == run_id
    assert body["strategy_id"] is not None
    assert body["version_id"] is not None

    get_resp = client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 200
    get_body = get_resp.json()

    assert get_body["strategy_id"] == body["strategy_id"]
    assert get_body["strategy_version_id"] == body["version_id"]
    assert get_body["strategy_name"] == "My Saved Draft"


def test_save_draft_run_as_strategy_requires_succeeded_run(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="runs-test@example.com",
    )

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "draft-run",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
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
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 200
    run_id = response.json()["id"]

    save_response = client.post(
        f"/runs/{run_id}/save-strategy",
        json={"name": "Saved too early"},
    )

    assert save_response.status_code == 400
    assert "Only succeeded unsaved runs can be saved as a strategy" in save_response.json()["detail"]


def test_create_run_rejects_draft_config_outside_plan_limit(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    plan = db_session.query(Plan).filter(Plan.code == "TEST_PRO").one()
    plan.max_backtest_years = 5
    db_session.commit()
    db_session.refresh(plan)

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "too-long-window",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2020-01-02",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
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
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 400
    assert "current plan limit" in response.json()["detail"]
    assert "shorten the range" in response.json()["detail"]


def test_create_run_rejects_draft_config_with_unsupported_symbol(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "unsupported-symbol",
                "tradable_symbol": "AAPL",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 400
    assert "not supported yet" in response.json()["detail"]
    assert "ETF-first" in response.json()["detail"]


def test_create_run_rejects_duplicate_active_draft_run(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    payload = {
        "draft_config": {
            "schema_version": "2.0",
            "name": "duplicate-check",
            "tradable_symbol": "QQQ",
            "benchmark_symbol": "QQQ",
            "reference_symbols": [],
            "start_date": "2021-04-14",
            "end_date": "2026-04-14",
            "initial_capital": 100000,
            "transaction_cost_bps": 5,
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
            "risk": {"cooldown_bars": 0},
            "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
        },
        "run_type": "SIMULATION",
        "executor_type": "SIMULATION_EXECUTOR",
        "request_payload": {},
        "max_attempts": 1,
    }

    first = client.post("/runs", json=payload)
    assert first.status_code == 200

    second = client.post("/runs", json=payload)
    assert second.status_code == 409

    detail = second.json()["detail"]
    assert detail["code"] == "DUPLICATE_ACTIVE_RUN"
    assert detail["message"] == "An equivalent run is already active."
    assert isinstance(detail["existing_run_id"], str)
    assert detail["existing_run_id"] == first.json()["id"]


def test_save_draft_run_as_strategy_revalidates_draft_config(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    run = create_run(
        db_session,
        current_user_ctx["id"],
        None,
        None,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {
            "draft_config": {
                "schema_version": "2.0",
                "name": "bad-save",
                "tradable_symbol": "AAPL",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            }
        },
        max_attempts=1,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 1.0},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary_json": "summary.json"},
    )

    response = client.post(
        f"/runs/{run.id}/save-strategy",
        json={"name": "Should fail"},
    )

    assert response.status_code == 400
    assert "not supported yet" in response.json()["detail"]
    assert "ETF-first" in response.json()["detail"]
