from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session, sessionmaker

from market_simulator.db.enums import RunStatus
from market_simulator.db.models.run import Run
from market_simulator.repositories.runs import (
    claim_next_queued_run,
    get_run,
    mark_run_failed,
    mark_run_succeeded,
    requeue_stale_running_runs,
    reset_run_to_queued,
    touch_run_heartbeat,
    update_run_progress,
)
from market_simulator.repositories.strategies import get_strategy_version
from market_simulator.service import SimulationService

from market_simulator.platform.services.artifact_store import (
    ArtifactStore,
    build_artifact_store,
)
from market_simulator.platform.services.parameter_sweep import (
    ParameterSweepService,
    SweepProgressEvent,
)
from market_simulator.platform.services.run_failure_policy import classify_run_exception


logger = logging.getLogger(__name__)


class RunWorkerService:
    def __init__(self, artifact_store: ArtifactStore | None = None):
        self.artifact_store = artifact_store or build_artifact_store()

    def _log_info(self, message: str, **fields):
        logger.info("%s | %s", message, fields)

    def _log_error(self, message: str, **fields):
        logger.error("%s | %s", message, fields)

    def _resolve_run_config(self, db: Session, run) -> tuple[dict, str]:
        if run.strategy_version_id is not None:
            strategy_version = get_strategy_version(db, run.strategy_version_id)
            if strategy_version is None:
                raise ValueError(f"Strategy version not found: {run.strategy_version_id}")
            return strategy_version.config_json, "Loaded saved strategy version"

        draft_config = (run.request_payload or {}).get("draft_config")
        if not isinstance(draft_config, dict):
            raise ValueError("Run does not contain draft_config")
        return draft_config, "Loaded unsaved draft config"

    def _resolve_sweep_base_config(self, db: Session, run) -> tuple[dict | None, str]:
        request_payload = run.request_payload or {}
        if isinstance(request_payload.get("base_config"), dict):
            return None, "Loaded sweep base_config"
        config_json, load_message = self._resolve_run_config(db, run)
        return config_json, load_message

    def _sweep_progress_pct(self, event: SweepProgressEvent) -> int:
        total_variants = max(event.total_variants, 1)
        if event.stage == "prepared":
            return 10
        if event.stage == "artifacts_finalizing":
            return 97
        if event.current_variant_index is None:
            return 10

        current_index = max(1, min(event.current_variant_index, total_variants))
        if event.stage == "variant_started":
            return 10 + int(((current_index - 1) / total_variants) * 85)
        return 10 + int((current_index / total_variants) * 85)

    def _update_sweep_progress(
        self,
        db: Session,
        run,
        *,
        progress_pct: int,
        progress_message: str,
        lease_seconds: int,
    ) -> None:
        progress_session_factory = sessionmaker(
            bind=db.get_bind(),
            autoflush=False,
            autocommit=False,
            future=True,
        )
        progress_db = progress_session_factory()
        try:
            latest_run = progress_db.get(Run, run.id)
            if latest_run is None:
                return
            if latest_run.status != RunStatus.RUNNING:
                return

            next_progress_pct = max(latest_run.progress_pct or 0, progress_pct)
            update_run_progress(
                progress_db,
                latest_run,
                progress_pct=next_progress_pct,
                progress_message=progress_message,
            )
            touch_run_heartbeat(progress_db, latest_run, lease_seconds=lease_seconds)
        finally:
            progress_db.close()

        db.expire(
            run,
            ["progress_pct", "progress_message", "heartbeat_at", "leased_until"],
        )
        self._log_info(
            "run progress checkpoint",
            run_id=str(run.id),
            worker_id=run.worker_id,
            progress_pct=next_progress_pct,
            progress_message=progress_message,
        )

    def _handle_execution_failure(
        self,
        db: Session,
        run,
        exc: Exception,
    ) -> None:
        latest_run = get_run(db, run.id)
        if latest_run is None:
            return

        if latest_run.status != RunStatus.RUNNING:
            return

        is_retryable, classification = classify_run_exception(exc)
        current_attempt = latest_run.attempt_count or 0
        max_attempts = latest_run.max_attempts or 1
        error_text = f"[{classification}] {str(exc)}"

        self._log_error(
            "run execution failed",
            run_id=str(latest_run.id),
            worker_id=latest_run.worker_id,
            attempt_count=current_attempt,
            max_attempts=max_attempts,
            classification=classification,
            error=str(exc),
        )

        if is_retryable and current_attempt < max_attempts:
            reset_run_to_queued(
                db,
                latest_run,
                message="Retry scheduled after retryable failure",
                error_message=error_text,
            )
            self._log_info(
                "run re-queued after retryable failure",
                run_id=str(latest_run.id),
                worker_id=latest_run.worker_id,
                attempt_count=current_attempt,
                max_attempts=max_attempts,
                classification=classification,
            )
            return

        mark_run_failed(db, latest_run, error_text)
        self._log_error(
            "run marked failed",
            run_id=str(latest_run.id),
            worker_id=latest_run.worker_id,
            attempt_count=current_attempt,
            max_attempts=max_attempts,
            classification=classification,
        )

    def execute_claimed_run(
        self,
        db: Session,
        run_id: str,
        *,
        lease_seconds: int = 300,
    ) -> dict:
        run = get_run(db, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        if run.status != RunStatus.RUNNING:
            raise ValueError(
                f"Run must be RUNNING before execution. Current status: {run.status}"
            )

        self._log_info(
            "starting claimed run execution",
            run_id=str(run.id),
            worker_id=run.worker_id,
            attempt_count=run.attempt_count,
            max_attempts=run.max_attempts,
            status=run.status,
        )

        try:
            if run.run_type == "PARAMETER_SWEEP" and run.executor_type != "SWEEP_EXECUTOR":
                raise ValueError(f"Unsupported executor_type for parameter sweep: {run.executor_type}")

            if run.executor_type == "SWEEP_EXECUTOR":
                if run.run_type != "PARAMETER_SWEEP":
                    raise ValueError(f"Unsupported run_type for sweep executor: {run.run_type}")

                request_payload = dict(run.request_payload or {})
                fallback_base_config, load_message = self._resolve_sweep_base_config(db, run)

                run_artifact_dir = self.artifact_store.prepare_run_directory(run.id)

                update_run_progress(
                    db,
                    run,
                    progress_pct=3,
                    progress_message="Worker started execution",
                )
                touch_run_heartbeat(db, run, lease_seconds=lease_seconds)
                self._log_info(
                    "run progress checkpoint",
                    run_id=str(run.id),
                    worker_id=run.worker_id,
                    progress_pct=3,
                    progress_message="Worker started execution",
                )

                update_run_progress(
                    db,
                    run,
                    progress_pct=6,
                    progress_message=load_message,
                )
                touch_run_heartbeat(db, run, lease_seconds=lease_seconds)
                self._log_info(
                    "run progress checkpoint",
                    run_id=str(run.id),
                    worker_id=run.worker_id,
                    progress_pct=6,
                    progress_message=load_message,
                )

                sweep_service = ParameterSweepService()

                def report_sweep_progress(event: SweepProgressEvent) -> None:
                    self._update_sweep_progress(
                        db,
                        run,
                        progress_pct=self._sweep_progress_pct(event),
                        progress_message=event.message or "Running parameter sweep",
                        lease_seconds=lease_seconds,
                    )

                result = sweep_service.run_sweep(
                    request_payload,
                    output_dir=run_artifact_dir,
                    fallback_base_config=fallback_base_config,
                    progress_callback=report_sweep_progress,
                )

                if (
                    (run.progress_pct or 0) < 97
                    or run.progress_message != "Finalizing sweep artifacts"
                ):
                    self._update_sweep_progress(
                        db,
                        run,
                        progress_pct=97,
                        progress_message="Finalizing sweep artifacts",
                        lease_seconds=lease_seconds,
                    )
                else:
                    touch_run_heartbeat(db, run, lease_seconds=lease_seconds)

                artifact_result = self.artifact_store.finalize_sweep_artifacts(run.id)

                mark_run_succeeded(
                    db=db,
                    run=run,
                    summary_json=result["summary"],
                    artifact_dir=artifact_result.artifact_dir,
                    artifact_manifest_json=artifact_result.manifest_json,
                    artifact_storage_type=artifact_result.storage_type,
                    artifact_root_uri=artifact_result.artifact_root_uri,
                )

                self._log_info(
                    "run succeeded",
                    run_id=str(run.id),
                    worker_id=run.worker_id,
                    attempt_count=run.attempt_count,
                    max_attempts=run.max_attempts,
                    artifact_dir=artifact_result.artifact_dir,
                )

                return {
                    "run_id": str(run.id),
                    "status": "SUCCEEDED",
                    "summary": result["summary"],
                    "artifact_dir": artifact_result.artifact_dir,
                    "artifact_manifest": artifact_result.manifest_json,
                }

            if run.executor_type != "SIMULATION_EXECUTOR":
                raise ValueError(f"Unsupported executor_type for now: {run.executor_type}")

            config_json, load_message = self._resolve_run_config(db, run)

            run_artifact_dir = self.artifact_store.prepare_run_directory(run.id)

            update_run_progress(
                db,
                run,
                progress_pct=5,
                progress_message="Worker started execution",
            )
            touch_run_heartbeat(db, run, lease_seconds=lease_seconds)
            self._log_info(
                "run progress checkpoint",
                run_id=str(run.id),
                worker_id=run.worker_id,
                progress_pct=5,
                progress_message="Worker started execution",
            )

            update_run_progress(
                db,
                run,
                progress_pct=15,
                progress_message=load_message,
            )
            touch_run_heartbeat(db, run, lease_seconds=lease_seconds)
            self._log_info(
                "run progress checkpoint",
                run_id=str(run.id),
                worker_id=run.worker_id,
                progress_pct=15,
                progress_message="Loaded strategy version",
            )

            service = SimulationService()

            update_run_progress(
                db,
                run,
                progress_pct=35,
                progress_message="Running simulation",
            )
            touch_run_heartbeat(db, run, lease_seconds=lease_seconds)
            self._log_info(
                "run progress checkpoint",
                run_id=str(run.id),
                worker_id=run.worker_id,
                progress_pct=35,
                progress_message="Running simulation",
            )

            result = service.run_from_config(
                config_json,
                output_dir=run_artifact_dir,
            )

            update_run_progress(
                db,
                run,
                progress_pct=85,
                progress_message="Finalizing artifacts",
            )
            touch_run_heartbeat(db, run, lease_seconds=lease_seconds)
            self._log_info(
                "run progress checkpoint",
                run_id=str(run.id),
                worker_id=run.worker_id,
                progress_pct=85,
                progress_message="Finalizing artifacts",
            )

            artifact_result = self.artifact_store.finalize_simulation_artifacts(run.id)

            mark_run_succeeded(
                db=db,
                run=run,
                summary_json=result.summary,
                artifact_dir=artifact_result.artifact_dir,
                artifact_manifest_json=artifact_result.manifest_json,
                artifact_storage_type=artifact_result.storage_type,
                artifact_root_uri=artifact_result.artifact_root_uri,
            )

            self._log_info(
                "run succeeded",
                run_id=str(run.id),
                worker_id=run.worker_id,
                attempt_count=run.attempt_count,
                max_attempts=run.max_attempts,
                artifact_dir=artifact_result.artifact_dir,
            )

            return {
                "run_id": str(run.id),
                "status": "SUCCEEDED",
                "summary": result.summary,
                "artifact_dir": artifact_result.artifact_dir,
                "artifact_manifest": artifact_result.manifest_json,
            }

        except Exception as exc:
            self._handle_execution_failure(db, run, exc)
            raise

    def claim_and_execute_next_run(
        self,
        db: Session,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> dict | None:
        run = claim_next_queued_run(
            db,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if run is None:
            return None

        self._log_info(
            "run claimed",
            run_id=str(run.id),
            worker_id=worker_id,
            attempt_count=run.attempt_count,
            max_attempts=run.max_attempts,
            status=run.status,
        )

        return self.execute_claimed_run(
            db,
            str(run.id),
            lease_seconds=lease_seconds,
        )

    def recover_stale_runs(self, db: Session) -> dict:
        recovered = requeue_stale_running_runs(db)

        for run in recovered:
            self._log_info(
                "stale run recovered",
                run_id=str(run.id),
                worker_id=run.worker_id,
                attempt_count=run.attempt_count,
                max_attempts=run.max_attempts,
                status=run.status,
                progress_message=run.progress_message,
            )

        return {
            "recovered_count": len(recovered),
            "run_ids": [str(run.id) for run in recovered],
        }


def build_worker_id(prefix: str = "worker") -> str:
    return f"{prefix}-{uuid.uuid4()}"
