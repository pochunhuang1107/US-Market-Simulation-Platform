import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from market_simulator.db.enums import ArtifactStorageType, RunStatus
from market_simulator.db.models.run import Run


TERMINAL_RUN_STATUSES = {
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_run(
    db: Session,
    user_id,
    strategy_id,
    strategy_version_id,
    run_type,
    executor_type,
    payload,
    *,
    max_attempts: int = 3,
):
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        run_type=run_type,
        executor_type=executor_type,
        status=RunStatus.PENDING,
        request_payload=payload,
        attempt_count=0,
        max_attempts=max_attempts,
        progress_pct=0,
        progress_message="Run created",
        artifact_storage_type=ArtifactStorageType.LOCAL,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id):
    return db.query(Run).filter(Run.id == run_id).first()


def get_run_for_user(db: Session, run_id, user_id):
    return (
        db.query(Run)
        .filter(Run.id == run_id, Run.user_id == user_id)
        .first()
    )


def _apply_run_filters(
    query,
    *,
    user_id,
    status: str | None = None,
    executor_type: str | None = None,
    run_type: str | None = None,
    strategy_id: str | None = None,
):
    query = query.filter(Run.user_id == user_id)

    if status is not None:
        query = query.filter(Run.status == status)

    if executor_type is not None:
        query = query.filter(Run.executor_type == executor_type)

    if run_type is not None:
        query = query.filter(Run.run_type == run_type)

    if strategy_id is not None:
        query = query.filter(Run.strategy_id == strategy_id)

    return query


def list_runs(
    db: Session,
    user_id,
    *,
    status: str | None = None,
    executor_type: str | None = None,
    run_type: str | None = None,
    strategy_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
):
    query = db.query(Run)
    query = _apply_run_filters(
        query,
        user_id=user_id,
        status=status,
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
    )

    return (
        query.order_by(Run.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_runs(
    db: Session,
    user_id,
    *,
    status: str | None = None,
    executor_type: str | None = None,
    run_type: str | None = None,
    strategy_id: str | None = None,
):
    query = db.query(func.count(Run.id))
    query = _apply_run_filters(
        query,
        user_id=user_id,
        status=status,
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
    )
    return query.scalar() or 0


def enqueue_run(db: Session, run: Run):
    if run.status not in {RunStatus.PENDING, RunStatus.FAILED}:
        raise ValueError(f"Run cannot be enqueued from status: {run.status}")

    now = utc_now()
    run.status = RunStatus.QUEUED
    run.queued_at = now
    run.heartbeat_at = now
    run.leased_until = None
    run.worker_id = None
    run.progress_pct = 0
    run.progress_message = "Run queued"
    run.error_message = None
    run.finished_at = None
    db.commit()
    db.refresh(run)
    return run


def mark_run_running(
    db: Session,
    run: Run,
    *,
    worker_id: str | None = None,
    lease_seconds: int = 300,
):
    if run.status != RunStatus.QUEUED:
        raise ValueError(f"Run cannot be marked RUNNING from status: {run.status}")

    now = utc_now()
    run.status = RunStatus.RUNNING
    run.started_at = run.started_at or now
    run.heartbeat_at = now
    run.leased_until = now + timedelta(seconds=lease_seconds)
    run.worker_id = worker_id
    run.attempt_count = (run.attempt_count or 0) + 1
    if run.progress_pct < 1:
        run.progress_pct = 1
    if not run.progress_message:
        run.progress_message = "Run started"
    db.commit()
    db.refresh(run)
    return run


def touch_run_heartbeat(
    db: Session,
    run: Run,
    *,
    lease_seconds: int = 300,
):
    if run.status != RunStatus.RUNNING:
        raise ValueError(f"Heartbeat only allowed for RUNNING runs. Current status: {run.status}")

    now = utc_now()
    run.heartbeat_at = now
    run.leased_until = now + timedelta(seconds=lease_seconds)
    db.commit()
    db.refresh(run)
    return run


def update_run_progress(
    db: Session,
    run: Run,
    *,
    progress_pct: int,
    progress_message: str | None = None,
):
    if run.status != RunStatus.RUNNING:
        raise ValueError(f"Progress update only allowed for RUNNING runs. Current status: {run.status}")

    bounded_progress = max(0, min(100, progress_pct))
    run.progress_pct = bounded_progress
    if progress_message is not None:
        run.progress_message = progress_message
    run.heartbeat_at = utc_now()
    db.commit()
    db.refresh(run)
    return run


def mark_run_succeeded(
    db: Session,
    run: Run,
    summary_json: dict,
    artifact_dir: str,
    artifact_manifest_json: dict,
    *,
    artifact_storage_type: str = ArtifactStorageType.LOCAL,
    artifact_root_uri: str | None = None,
):
    if run.status != RunStatus.RUNNING:
        raise ValueError(f"Run cannot be marked SUCCEEDED from status: {run.status}")

    now = utc_now()
    resolved_artifact_root_uri = artifact_root_uri or artifact_dir

    run.status = RunStatus.SUCCEEDED
    run.summary_json = summary_json
    run.artifact_dir = artifact_dir
    run.artifact_manifest_json = artifact_manifest_json
    run.artifact_storage_type = artifact_storage_type
    run.artifact_root_uri = resolved_artifact_root_uri
    run.progress_pct = 100
    run.progress_message = "Run completed"
    run.heartbeat_at = now
    run.leased_until = None
    run.finished_at = now
    run.error_message = None
    db.commit()
    db.refresh(run)
    return run


def mark_run_failed(db: Session, run: Run, error_message: str):
    if run.status in TERMINAL_RUN_STATUSES:
        raise ValueError(f"Run cannot be marked FAILED from terminal status: {run.status}")

    now = utc_now()
    run.status = RunStatus.FAILED
    run.error_message = error_message
    run.progress_message = "Run failed"
    run.heartbeat_at = now
    run.leased_until = None
    run.finished_at = now
    db.commit()
    db.refresh(run)
    return run


def mark_run_canceled(db: Session, run: Run, message: str | None = None):
    if run.status not in {RunStatus.PENDING, RunStatus.QUEUED}:
        raise ValueError(f"Run cannot be canceled from status: {run.status}")

    now = utc_now()
    run.status = RunStatus.CANCELED
    run.progress_message = message or "Run canceled"
    run.heartbeat_at = now
    run.leased_until = None
    run.finished_at = now
    run.error_message = None
    db.commit()
    db.refresh(run)
    return run


def reset_run_to_queued(
    db: Session,
    run: Run,
    *,
    message: str = "Run re-queued",
    error_message: str | None = None,
):
    if run.status not in {RunStatus.RUNNING, RunStatus.FAILED}:
        raise ValueError(f"Run cannot be reset to QUEUED from status: {run.status}")

    now = utc_now()
    run.status = RunStatus.QUEUED
    run.queued_at = now
    run.heartbeat_at = now
    run.leased_until = None
    run.worker_id = None
    run.progress_message = message
    run.error_message = error_message
    run.finished_at = None
    db.commit()
    db.refresh(run)
    return run


def claim_next_queued_run(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int = 300,
):
    now = utc_now()

    stmt = (
        select(Run)
        .where(Run.status == RunStatus.QUEUED)
        .where(
            or_(
                Run.leased_until.is_(None),
                Run.leased_until < now,
            )
        )
        .order_by(Run.queued_at.asc(), Run.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )

    run = db.execute(stmt).scalars().first()
    if run is None:
        db.rollback()
        return None

    run.status = RunStatus.RUNNING
    run.started_at = run.started_at or now
    run.heartbeat_at = now
    run.leased_until = now + timedelta(seconds=lease_seconds)
    run.worker_id = worker_id
    run.attempt_count = (run.attempt_count or 0) + 1
    run.progress_pct = max(run.progress_pct or 0, 1)
    run.progress_message = "Run claimed by worker"

    db.commit()
    db.refresh(run)
    return run


def requeue_stale_running_runs(
    db: Session,
    *,
    limit: int = 100,
):
    now = utc_now()

    stmt = (
        select(Run)
        .where(Run.status == RunStatus.RUNNING)
        .where(Run.leased_until.is_not(None))
        .where(Run.leased_until < now)
        .order_by(Run.leased_until.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )

    stale_runs = list(db.execute(stmt).scalars().all())
    if not stale_runs:
        db.rollback()
        return []

    for run in stale_runs:
        if (run.attempt_count or 0) < (run.max_attempts or 1):
            run.status = RunStatus.QUEUED
            run.queued_at = now
            run.heartbeat_at = now
            run.leased_until = None
            run.worker_id = None
            run.progress_message = "Stale run re-queued"
            run.error_message = "Worker lease expired; retry scheduled"
            run.finished_at = None
        else:
            run.status = RunStatus.FAILED
            run.heartbeat_at = now
            run.leased_until = None
            run.finished_at = now
            run.progress_message = "Run failed after lease expiry"
            run.error_message = "Worker lease expired and max attempts reached"

    db.commit()

    for run in stale_runs:
        db.refresh(run)

    return stale_runs