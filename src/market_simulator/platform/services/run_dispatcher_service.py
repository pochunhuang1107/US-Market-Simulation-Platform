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

        if run.strategy_version_id is None:
            raise ValueError("Run does not have strategy_version_id")

        if run.executor_type != "SIMULATION_EXECUTOR":
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