import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from market_simulator.db.enums import RunStatus
from market_simulator.db.models.run import Run


def create_run(db: Session, user_id, strategy_id, strategy_version_id, run_type, executor_type, payload):
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        run_type=run_type,
        executor_type=executor_type,
        status=RunStatus.PENDING,
        request_payload=payload,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id):
    return db.query(Run).filter(Run.id == run_id).first()


def list_runs(db: Session, user_id):
    return db.query(Run).filter(Run.user_id == user_id).all()


def mark_run_running(db: Session, run: Run):
    run.status = RunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def mark_run_succeeded(db: Session, run: Run, summary_json: dict, artifact_dir: str, artifact_manifest_json: dict):
    run.status = RunStatus.SUCCEEDED
    run.summary_json = summary_json
    run.artifact_dir = artifact_dir
    run.artifact_manifest_json = artifact_manifest_json
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def mark_run_failed(db: Session, run: Run, error_message: str):
    run.status = RunStatus.FAILED
    run.error_message = error_message
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run