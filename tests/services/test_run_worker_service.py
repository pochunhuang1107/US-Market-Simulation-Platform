from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from market_simulator.db.enums import RunStatus
from market_simulator.platform.services.run_failure_policy import RetryableRunError
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import (
    create_run,
    enqueue_run,
    get_run,
)


@dataclass
class FakeSimulationResult:
    summary: dict


class FakeArtifactStore:
    def prepare_run_directory(self, run_id):
        return "/tmp/fake-run-dir"

    def finalize_simulation_artifacts(self, run_id):
        class Result:
            storage_type = "LOCAL"
            artifact_dir = f"/tmp/runs/{run_id}"
            artifact_root_uri = f"/tmp/runs/{run_id}"
            manifest_json = {
                "summary": f"/tmp/runs/{run_id}/summary.json",
                "timeline": f"/tmp/runs/{run_id}/timeline.csv",
            }

        return Result()


def test_claim_and_execute_next_run_succeeds(
    monkeypatch,
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(email="worker-success@example.com")
    strategy, version = create_strategy_bundle(user_id=str(user.id))

    class FakeSimulationService:
        def run_from_config(self, config_json, output_dir):
            return FakeSimulationResult(summary={"name": "test", "total_return_pct": 12.34})

    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.SimulationService",
        FakeSimulationService,
    )

    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "worker success"},
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())
    result = service.claim_and_execute_next_run(
        db_session,
        worker_id="worker-test-1",
        lease_seconds=300,
    )

    refreshed = get_run(db_session, run.id)

    assert result is not None
    assert result["status"] == "SUCCEEDED"
    assert refreshed.status == RunStatus.SUCCEEDED
    assert refreshed.attempt_count == 1
    assert refreshed.progress_pct == 100
    assert refreshed.summary_json["name"] == "test"
    assert refreshed.artifact_root_uri == f"/tmp/runs/{run.id}"


def test_bad_executor_marks_run_failed_non_retryable(
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(email="worker-fail@example.com")
    strategy, version = create_strategy_bundle(user_id=str(user.id))

    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "BAD_EXECUTOR",
        {"note": "bad executor"},
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())

    with pytest.raises(ValueError, match="Unsupported executor_type"):
        service.claim_and_execute_next_run(
            db_session,
            worker_id="worker-test-2",
            lease_seconds=300,
        )

    refreshed = get_run(db_session, run.id)
    assert refreshed.status == RunStatus.FAILED
    assert refreshed.attempt_count == 1
    assert refreshed.progress_message == "Run failed"
    assert refreshed.error_message.startswith("[NON_RETRYABLE]")


def test_retryable_failure_requeues_run_when_attempts_remain(
    monkeypatch,
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(email="worker-retry@example.com")
    strategy, version = create_strategy_bundle(user_id=str(user.id))

    class FakeSimulationService:
        def run_from_config(self, config_json, output_dir):
            raise RetryableRunError("temporary timeout while reading data")

    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.SimulationService",
        FakeSimulationService,
    )

    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "retryable"},
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())

    with pytest.raises(RetryableRunError):
        service.claim_and_execute_next_run(
            db_session,
            worker_id="worker-test-3",
            lease_seconds=300,
        )

    refreshed = get_run(db_session, run.id)
    assert refreshed.status == RunStatus.QUEUED
    assert refreshed.attempt_count == 1
    assert refreshed.progress_message == "Retry scheduled after retryable failure"
    assert refreshed.error_message.startswith("[RETRYABLE]")


def test_recover_stale_runs_requeues_expired_run(
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(email="worker-stale@example.com")
    strategy, version = create_strategy_bundle(user_id=str(user.id))

    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "stale"},
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    run.status = RunStatus.RUNNING
    run.worker_id = "worker-stale"
    run.attempt_count = 1
    run.leased_until = run.created_at - timedelta(minutes=1)
    db_session.commit()
    db_session.refresh(run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())
    result = service.recover_stale_runs(db_session)

    refreshed = get_run(db_session, run.id)
    assert result["recovered_count"] == 1
    assert str(run.id) in result["run_ids"]
    assert refreshed.status == RunStatus.QUEUED
    assert refreshed.progress_message == "Stale run re-queued"
    assert refreshed.error_message == "Worker lease expired; retry scheduled"