from __future__ import annotations

import uuid

from market_simulator.db.enums import RunStatus
from market_simulator.repositories.runs import create_run, mark_run_succeeded


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
    assert body["attempt_count"] == 0
    assert body["max_attempts"] == 3
    assert body["progress_message"] == "Run created"


def test_list_runs_returns_items_wrapper(
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
            "request_payload": {"note": "list test"},
            "max_attempts": 3,
        },
    )
    assert create_resp.status_code == 200

    response = client.get("/runs")
    assert response.status_code == 200

    body = response.json()
    assert "items" in body
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "PENDING"


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