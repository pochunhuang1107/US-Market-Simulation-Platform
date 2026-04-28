from __future__ import annotations

from sqlalchemy.orm import Session

from market_simulator.db.enums import RunStatus
from market_simulator.repositories.runs import (
    enqueue_run,
    get_run_for_user,
    mark_run_canceled,
)


class RunDispatcherService:
    def dispatch_run(self, db: Session, run_id: str, user_id: str) -> dict:
        run = get_run_for_user(db, run_id, user_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        if run.status not in {RunStatus.PENDING, RunStatus.FAILED}:
            raise ValueError(f"Run cannot be enqueued from status: {run.status}")

        request_payload = run.request_payload or {}
        has_saved_strategy_version = run.strategy_version_id is not None
        has_draft_config = isinstance(request_payload.get("draft_config"), dict)
        has_sweep_base_config = (
            run.run_type == "PARAMETER_SWEEP"
            and isinstance(request_payload.get("base_config"), dict)
        )

        if not has_saved_strategy_version and not has_draft_config and not has_sweep_base_config:
            raise ValueError("Run does not have a saved strategy version, draft_config, or base_config")

        allowed_executor = (
            "SWEEP_EXECUTOR" if run.run_type == "PARAMETER_SWEEP" else "SIMULATION_EXECUTOR"
        )
        if run.executor_type != allowed_executor:
            raise ValueError(f"Unsupported executor_type for now: {run.executor_type}")

        enqueue_run(db, run)

        return {
            "run_id": str(run.id),
            "status": str(run.status),
            "message": "Run queued successfully",
        }

    def cancel_run(self, db: Session, run_id: str, user_id: str) -> dict:
        run = get_run_for_user(db, run_id, user_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        if run.status not in {RunStatus.PENDING, RunStatus.QUEUED}:
            raise ValueError(f"Run cannot be canceled from status: {run.status}")

        mark_run_canceled(db, run, "Run canceled by user request")

        return {
            "run_id": str(run.id),
            "status": str(run.status),
            "message": "Run canceled successfully",
        }
