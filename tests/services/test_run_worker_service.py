from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from market_simulator.db.enums import RunStatus
from market_simulator.platform.services.parameter_sweep import SweepProgressEvent
from market_simulator.platform.services.run_failure_policy import RetryableRunError
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories import runs as runs_repo
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


def test_claim_and_execute_reference_run_sets_version_reference(
    monkeypatch,
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(email="worker-reference-success@example.com")
    strategy, version = create_strategy_bundle(user_id=str(user.id))

    class FakeSimulationService:
        def run_from_config(self, config_json, output_dir):
            return FakeSimulationResult(summary={"name": "reference", "total_return_pct": 21.0})

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
        {
            "source": "strategy_version_reference_run",
            "set_as_reference_on_success": True,
            "reference_strategy_version_id": str(version.id),
        },
        max_attempts=1,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())
    result = service.claim_and_execute_next_run(
        db_session,
        worker_id="worker-reference-test",
        lease_seconds=300,
    )

    db_session.refresh(version)
    refreshed = get_run(db_session, run.id)

    assert result is not None
    assert refreshed.status == RunStatus.SUCCEEDED
    assert version.reference_run_id == refreshed.id


def test_simulation_run_progress_checkpoints_remain_unchanged(
    monkeypatch,
    db_session,
    create_user,
    create_strategy_bundle,
):
    user = create_user(email="worker-simulation-progress@example.com")
    strategy, version = create_strategy_bundle(user_id=str(user.id))
    progress_updates: list[tuple[int, str | None]] = []

    class FakeSimulationService:
        def run_from_config(self, config_json, output_dir):
            return FakeSimulationResult(summary={"name": "test", "total_return_pct": 12.34})

    def record_update_run_progress(db, run, *, progress_pct, progress_message=None):
        progress_updates.append((progress_pct, progress_message))
        return runs_repo.update_run_progress(
            db,
            run,
            progress_pct=progress_pct,
            progress_message=progress_message,
        )

    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.SimulationService",
        FakeSimulationService,
    )
    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.update_run_progress",
        record_update_run_progress,
    )

    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "worker progress"},
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeArtifactStore())
    service.claim_and_execute_next_run(
        db_session,
        worker_id="worker-simulation-progress",
        lease_seconds=300,
    )

    assert progress_updates == [
        (5, "Worker started execution"),
        (15, "Loaded saved strategy version"),
        (35, "Running simulation"),
        (85, "Finalizing artifacts"),
    ]


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
    progress_updates: list[tuple[int, str | None]] = []
    persisted_progress_snapshots: list[tuple[int, str | None]] = []
    progress_reader_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        future=True,
    )

    class FakeParameterSweepService:
        def run_sweep(
            self,
            payload,
            output_dir,
            fallback_base_config=None,
            progress_callback=None,
        ):
            assert payload["grid"] == {"entry_rule.threshold": [20, 25]}
            assert fallback_base_config is None
            assert output_dir == "/tmp/fake-run-dir"

            def emit(event: SweepProgressEvent) -> None:
                assert progress_callback is not None
                progress_callback(event)
                reader_db = progress_reader_factory()
                try:
                    refreshed = get_run(reader_db, run.id)
                    persisted_progress_snapshots.append(
                        (refreshed.progress_pct, refreshed.progress_message)
                    )
                finally:
                    reader_db.close()

            if progress_callback is not None:
                emit(
                    SweepProgressEvent(
                        stage="prepared",
                        current_variant_index=None,
                        total_variants=2,
                        message="Prepared 2 sweep variants",
                    )
                )
                emit(
                    SweepProgressEvent(
                        stage="variant_started",
                        current_variant_index=1,
                        total_variants=2,
                        variant_id="variant-1",
                        variant_name="Variant 1",
                        message="Running sweep variant 1 of 2",
                    )
                )
                emit(
                    SweepProgressEvent(
                        stage="variant_completed",
                        current_variant_index=1,
                        total_variants=2,
                        variant_id="variant-1",
                        variant_name="Variant 1",
                        message="Completed sweep variant 1 of 2",
                    )
                )
                emit(
                    SweepProgressEvent(
                        stage="variant_started",
                        current_variant_index=2,
                        total_variants=2,
                        variant_id="variant-2",
                        variant_name="Variant 2",
                        message="Running sweep variant 2 of 2",
                    )
                )
                emit(
                    SweepProgressEvent(
                        stage="variant_completed",
                        current_variant_index=2,
                        total_variants=2,
                        variant_id="variant-2",
                        variant_name="Variant 2",
                        message="Completed sweep variant 2 of 2",
                    )
                )
                emit(
                    SweepProgressEvent(
                        stage="artifacts_finalizing",
                        current_variant_index=None,
                        total_variants=2,
                        message="Finalizing sweep artifacts",
                    )
                )
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

    def record_update_run_progress(db, run, *, progress_pct, progress_message=None):
        progress_updates.append((progress_pct, progress_message))
        return runs_repo.update_run_progress(
            db,
            run,
            progress_pct=progress_pct,
            progress_message=progress_message,
        )

    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.ParameterSweepService",
        FakeParameterSweepService,
    )
    monkeypatch.setattr(
        "market_simulator.platform.services.run_worker_service.update_run_progress",
        record_update_run_progress,
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
    assert refreshed.artifact_manifest_json["sweep_summary"].endswith(
        "sweep_summary.json"
    )
    assert progress_updates == [
        (3, "Worker started execution"),
        (6, "Loaded sweep base_config"),
        (10, "Prepared 2 sweep variants"),
        (10, "Running sweep variant 1 of 2"),
        (52, "Completed sweep variant 1 of 2"),
        (52, "Running sweep variant 2 of 2"),
        (95, "Completed sweep variant 2 of 2"),
        (97, "Finalizing sweep artifacts"),
    ]
    assert [pct for pct, _message in progress_updates] == sorted(
        pct for pct, _message in progress_updates
    )
    assert persisted_progress_snapshots == [
        (10, "Prepared 2 sweep variants"),
        (10, "Running sweep variant 1 of 2"),
        (52, "Completed sweep variant 1 of 2"),
        (52, "Running sweep variant 2 of 2"),
        (95, "Completed sweep variant 2 of 2"),
        (97, "Finalizing sweep artifacts"),
    ]


def test_parameter_sweep_persists_rewritten_artifact_summary_from_store(
    monkeypatch,
    db_session,
    create_user,
):
    user = create_user(email="worker-sweep-s3-summary@example.com")

    class FakeParameterSweepService:
        def run_sweep(
            self,
            payload,
            output_dir,
            fallback_base_config=None,
            progress_callback=None,
        ):
            return {
                "summary": {
                    "run_type": "PARAMETER_SWEEP",
                    "variant_count": 1,
                    "best_variant": {
                        "variant_id": "variant-1",
                        "artifact_dir": "/tmp/fake-run-dir/variants/001_variant-1",
                    },
                    "results": [
                        {
                            "variant_id": "variant-1",
                            "artifact_dir": "/tmp/fake-run-dir/variants/001_variant-1",
                        }
                    ],
                },
                "results": [],
            }

    class FakeRewritingArtifactStore(FakeArtifactStore):
        def finalize_sweep_artifacts(self, run_id):
            class Result:
                storage_type = "S3"
                artifact_dir = f"/tmp/runs/{run_id}"
                artifact_root_uri = f"s3://unit-test-bucket/artifacts/runs/{run_id}"
                manifest_json = {
                    "sweep_summary": f"s3://unit-test-bucket/artifacts/runs/{run_id}/sweep_summary.json",
                    "sweep_results": f"s3://unit-test-bucket/artifacts/runs/{run_id}/sweep_results.csv",
                }
                summary_json = {
                    "run_type": "PARAMETER_SWEEP",
                    "variant_count": 1,
                    "best_variant": {
                        "variant_id": "variant-1",
                        "artifact_dir": f"s3://unit-test-bucket/artifacts/runs/{run_id}/variants/001_variant-1",
                    },
                    "results": [
                        {
                            "variant_id": "variant-1",
                            "artifact_dir": f"s3://unit-test-bucket/artifacts/runs/{run_id}/variants/001_variant-1",
                        }
                    ],
                }

            return Result()

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
            "grid": {"entry_rule.threshold": [20]},
        },
        max_attempts=3,
    )
    enqueue_run(db_session, run)

    service = RunWorkerService(artifact_store=FakeRewritingArtifactStore())
    result = service.claim_and_execute_next_run(
        db_session,
        worker_id="worker-sweep-s3-summary",
        lease_seconds=300,
    )

    refreshed = get_run(db_session, run.id)

    assert result["summary"]["results"][0]["artifact_dir"].startswith("s3://")
    assert refreshed.summary_json["results"][0]["artifact_dir"].startswith("s3://")
    assert "/tmp/fake-run-dir" not in str(refreshed.summary_json)
