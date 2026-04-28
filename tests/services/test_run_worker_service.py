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

    def finalize_sweep_artifacts(self, run_id):
        class Result:
            storage_type = "LOCAL"
            artifact_dir = f"/tmp/runs/{run_id}"
            artifact_root_uri = f"/tmp/runs/{run_id}"
            manifest_json = {
                "sweep_summary": f"/tmp/runs/{run_id}/sweep_summary.json",
                "sweep_results": f"/tmp/runs/{run_id}/sweep_results.csv",
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


def test_claim_and_execute_next_run_succeeds_for_unsaved_draft_config(
    monkeypatch,
    db_session,
    create_user,
):
    user = create_user(email="worker-draft@example.com")

    class FakeSimulationService:
        def run_from_config(self, config_json, output_dir):
            assert config_json["tradable_symbol"] == "QQQ"
            return FakeSimulationResult(summary={"name": "draft", "total_return_pct": 8.76})

    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.SimulationService",
        FakeSimulationService,
    )

    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {
            "draft_config": {
                "name": "draft-run",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "start_date": "2019-01-02",
                "end_date": "2024-12-31",
                "initial_capital": 100000,
            }
        },
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())
    result = service.claim_and_execute_next_run(
        db_session,
        worker_id="worker-draft-1",
        lease_seconds=300,
    )

    refreshed = get_run(db_session, run.id)

    assert result is not None
    assert result["status"] == "SUCCEEDED"
    assert refreshed.status == RunStatus.SUCCEEDED
    assert refreshed.strategy_id is None
    assert refreshed.strategy_version_id is None
    assert refreshed.summary_json["name"] == "draft"


def test_claim_and_execute_next_run_succeeds_for_parameter_sweep(
    monkeypatch,
    db_session,
    create_user,
):
    user = create_user(email="worker-sweep@example.com")

    class FakeParameterSweepService:
        def run_sweep(self, payload, output_dir, fallback_base_config=None):
            assert payload["grid"] == {"entry_rule.threshold": [20, 25]}
            assert fallback_base_config is None
            assert output_dir == "/tmp/fake-run-dir"
            return {
                "summary": {
                    "run_type": "PARAMETER_SWEEP",
                    "variant_count": 2,
                    "succeeded_count": 2,
                    "failed_count": 0,
                    "ranking_metric": "sharpe_ratio",
                    "best_variant": {"variant_name": "best"},
                },
                "results": [],
            }

    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.ParameterSweepService",
        FakeParameterSweepService,
    )

    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {
            "base_config": {
                "name": "qqq-rsi",
            },
            "grid": {"entry_rule.threshold": [20, 25]},
        },
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())
    result = service.claim_and_execute_next_run(
        db_session,
        worker_id="worker-sweep-1",
        lease_seconds=300,
    )

    refreshed = get_run(db_session, run.id)

    assert result is not None
    assert result["status"] == "SUCCEEDED"
    assert refreshed.status == RunStatus.SUCCEEDED
    assert refreshed.summary_json["variant_count"] == 2
    assert refreshed.artifact_manifest_json["sweep_summary"].endswith("sweep_summary.json")
