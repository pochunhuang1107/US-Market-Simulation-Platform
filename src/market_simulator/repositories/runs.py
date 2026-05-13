import json
import hashlib
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from market_simulator.db.enums import ArtifactStorageType, RunStatus
from market_simulator.db.models.run import Run
from market_simulator.db.models.strategy import Strategy, StrategyVersion
from market_simulator.settings import get_settings


TERMINAL_RUN_STATUSES = {
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


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
    parent_run_id=None,
):
    artifact_storage_backend = (
        get_settings().artifact_storage_backend or ArtifactStorageType.LOCAL
    ).strip().upper()
    artifact_storage_type = (
        ArtifactStorageType.S3
        if artifact_storage_backend == ArtifactStorageType.S3.value
        else ArtifactStorageType.LOCAL
    )
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        parent_run_id=parent_run_id,
        run_type=run_type,
        executor_type=executor_type,
        status=RunStatus.PENDING,
        request_payload=payload,
        attempt_count=0,
        max_attempts=max_attempts,
        progress_pct=0,
        progress_message="Run created",
        artifact_storage_type=artifact_storage_type,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def link_run_to_strategy_version(
    db: Session,
    run: Run,
    *,
    strategy_id,
    strategy_version_id,
):
    run.strategy_id = strategy_id
    run.strategy_version_id = strategy_version_id
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id):
    return db.query(Run).filter(Run.id == run_id).first()


def get_run_for_user(db: Session, run_id, user_id):
    return (
        db.query(Run)
        .options(
            joinedload(Run.strategy),
            joinedload(Run.strategy_version),
        )
        .filter(Run.id == run_id, Run.user_id == user_id)
        .first()
    )


def find_saved_sweep_variant_run(db: Session, *, user_id, sweep_run_id, variant_id: str):
    child_runs = (
        db.query(Run)
        .options(
            joinedload(Run.strategy),
            joinedload(Run.strategy_version),
        )
        .filter(
            Run.user_id == user_id,
            Run.parent_run_id == sweep_run_id,
            Run.strategy_id.isnot(None),
            Run.strategy_version_id.isnot(None),
        )
        .order_by(Run.created_at.desc())
        .all()
    )

    for run in child_runs:
        payload = run.request_payload or {}
        if (
            payload.get("source") == "sweep_variant_save"
            and str(payload.get("source_sweep_run_id")) == str(sweep_run_id)
            and str(payload.get("source_variant_id")) == str(variant_id)
        ):
            return run

    return None


def find_duplicate_active_run(
    db: Session,
    *,
    user_id,
    strategy_id,
    strategy_version_id,
    run_type,
    executor_type,
    request_payload: dict,
):
    target_hash = _hash_payload(request_payload)

    candidate_runs = (
        db.query(Run)
        .options(
            joinedload(Run.strategy),
            joinedload(Run.strategy_version),
        )
        .filter(Run.user_id == user_id)
        .filter(Run.strategy_id == strategy_id)
        .filter(Run.strategy_version_id == strategy_version_id)
        .filter(Run.run_type == run_type)
        .filter(Run.executor_type == executor_type)
        .filter(Run.status.in_([RunStatus.PENDING, RunStatus.QUEUED, RunStatus.RUNNING]))
        .all()
    )

    for run in candidate_runs:
        payload = run.request_payload or {}
        if _hash_payload(payload) == target_hash:
            return run

    return None


def _apply_run_filters(
    query,
    *,
    user_id,
    status: str | Sequence[str] | None = None,
    executor_type: str | None = None,
    run_type: str | None = None,
    strategy_id: str | None = None,
    artifact_storage_type: str | None = None,
    include_derived_results: bool = True,
):
    query = query.filter(Run.user_id == user_id)

    if not include_derived_results:
        source = Run.request_payload.op("->>")("source")
        query = query.filter(or_(source.is_(None), source != "sweep_variant_save"))

    if status is not None:
        if isinstance(status, str):
            query = query.filter(Run.status == status)
        else:
            query = query.filter(Run.status.in_(status))

    if executor_type is not None:
        query = query.filter(Run.executor_type == executor_type)

    if run_type is not None:
        query = query.filter(Run.run_type == run_type)

    if strategy_id is not None:
        query = query.filter(Run.strategy_id == strategy_id)

    if artifact_storage_type is not None:
        query = query.filter(Run.artifact_storage_type == artifact_storage_type)

    return query


def list_runs(
    db: Session,
    user_id,
    *,
    status: str | Sequence[str] | None = None,
    executor_type: str | None = None,
    run_type: str | None = None,
    strategy_id: str | None = None,
    artifact_storage_type: str | None = None,
    include_derived_results: bool = True,
    offset: int = 0,
    limit: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    query = db.query(Run).options(
        joinedload(Run.strategy),
        joinedload(Run.strategy_version),
    )
    query = _apply_run_filters(
        query,
        user_id=user_id,
        status=status,
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
        artifact_storage_type=artifact_storage_type,
        include_derived_results=include_derived_results,
    )

    sort_column = {
        "created_at": Run.created_at,
        "finished_at": Run.finished_at,
        "status": Run.status,
    }.get(sort_by, Run.created_at)

    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    return query.offset(offset).limit(limit).all()


def count_runs(
    db: Session,
    user_id,
    *,
    status: str | Sequence[str] | None = None,
    executor_type: str | None = None,
    run_type: str | None = None,
    strategy_id: str | None = None,
    artifact_storage_type: str | None = None,
    include_derived_results: bool = True,
):
    query = db.query(func.count(Run.id))
    query = _apply_run_filters(
        query,
        user_id=user_id,
        status=status,
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
        artifact_storage_type=artifact_storage_type,
        include_derived_results=include_derived_results,
    )
    return query.scalar() or 0


def get_run_queue_health(
    db: Session,
    *,
    running_stale_seconds: int = 300,
    queue_oldest_warning_seconds: int = 600,
    failed_recent_seconds: int = 86400,
) -> dict:
    now = utc_now()
    stale_cutoff = now - timedelta(seconds=running_stale_seconds)
    old_queue_cutoff = now - timedelta(seconds=queue_oldest_warning_seconds)
    failed_recent_cutoff = now - timedelta(seconds=failed_recent_seconds)
    stale_running_condition = (
        (Run.status == RunStatus.RUNNING)
        & (
            (Run.leased_until < now)
            | (
                Run.leased_until.is_(None)
                & (
                    Run.heartbeat_at.is_(None)
                    | (Run.heartbeat_at < stale_cutoff)
                )
            )
            | (Run.heartbeat_at < stale_cutoff)
        )
    )
    old_pending_condition = (
        (Run.status == RunStatus.PENDING)
        & (Run.created_at < old_queue_cutoff)
    )
    old_queued_condition = (
        (Run.status == RunStatus.QUEUED)
        & (
            (Run.queued_at < old_queue_cutoff)
            | (Run.queued_at.is_(None) & (Run.created_at < old_queue_cutoff))
        )
    )
    failed_recent_condition = (
        (Run.status == RunStatus.FAILED)
        & (
            (Run.finished_at >= failed_recent_cutoff)
            | (Run.finished_at.is_(None) & (Run.updated_at >= failed_recent_cutoff))
        )
    )

    row = db.execute(
        select(
            func.coalesce(
                func.sum(case((Run.status == RunStatus.PENDING, 1), else_=0)),
                0,
            ).label("pending_count"),
            func.coalesce(
                func.sum(case((Run.status == RunStatus.QUEUED, 1), else_=0)),
                0,
            ).label("queued_count"),
            func.coalesce(
                func.sum(case((Run.status == RunStatus.RUNNING, 1), else_=0)),
                0,
            ).label("running_count"),
            func.coalesce(
                func.sum(case((stale_running_condition, 1), else_=0)),
                0,
            ).label("stale_running_count"),
            func.coalesce(
                func.sum(case((failed_recent_condition, 1), else_=0)),
                0,
            ).label("failed_recent_count"),
            func.coalesce(
                func.sum(case((old_pending_condition, 1), else_=0)),
                0,
            ).label("suspicious_old_pending_count"),
            func.coalesce(
                func.sum(case((old_queued_condition, 1), else_=0)),
                0,
            ).label("suspicious_old_queued_count"),
            func.min(
                case((Run.status == RunStatus.PENDING, Run.created_at), else_=None)
            ).label("oldest_pending_at"),
            func.min(
                case(
                    (
                        Run.status == RunStatus.QUEUED,
                        func.coalesce(Run.queued_at, Run.created_at),
                    ),
                    else_=None,
                )
            ).label("oldest_queued_at"),
            func.min(
                case((Run.status == RunStatus.RUNNING, Run.heartbeat_at), else_=None)
            ).label("oldest_running_heartbeat_at"),
        )
    ).one()

    oldest_pending_age_seconds = _age_seconds(row.oldest_pending_at, now)
    oldest_queued_age_seconds = _age_seconds(row.oldest_queued_at, now)
    oldest_running_heartbeat_age_seconds = _age_seconds(
        row.oldest_running_heartbeat_at,
        now,
    )

    return {
        "pending_count": int(row.pending_count),
        "queued_count": int(row.queued_count),
        "running_count": int(row.running_count),
        "stale_running_count": int(row.stale_running_count),
        "failed_recent_count": int(row.failed_recent_count),
        "suspicious_old_pending_count": int(row.suspicious_old_pending_count),
        "suspicious_old_queued_count": int(row.suspicious_old_queued_count),
        "suspicious_old_running_count": int(row.stale_running_count),
        "oldest_pending_age_seconds": oldest_pending_age_seconds,
        "oldest_queued_age_seconds": oldest_queued_age_seconds,
        "oldest_running_heartbeat_age_seconds": (
            oldest_running_heartbeat_age_seconds
        ),
        "failed_recent_window_seconds": failed_recent_seconds,
        "worker_recovery_available": True,
    }


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now - value).total_seconds()))


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
    if run.strategy_version_id is not None and run.run_type == "SIMULATION":
        request_payload = run.request_payload or {}
        reference_strategy_version_id = request_payload.get("reference_strategy_version_id")
        target_version_id = reference_strategy_version_id or run.strategy_version_id
        should_set_reference = (
            request_payload.get("set_as_reference_on_success") is True
            or request_payload.get("source") == "strategy_version_reference_run"
            or str(reference_strategy_version_id) == str(run.strategy_version_id)
        )
        version = None
        if should_set_reference and str(target_version_id) == str(run.strategy_version_id):
            version = (
                db.query(StrategyVersion)
                .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
                .filter(
                    StrategyVersion.id == target_version_id,
                    StrategyVersion.reference_run_id.is_(None),
                    StrategyVersion.strategy_id == run.strategy_id,
                    Strategy.user_id == run.user_id,
                )
                .first()
            )
        if version is not None:
            version.reference_run_id = run.id
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
    running_stale_seconds: int = 300,
):
    now = utc_now()
    stale_cutoff = now - timedelta(seconds=running_stale_seconds)

    stmt = (
        select(Run)
        .where(Run.status == RunStatus.RUNNING)
        .where(
            (Run.leased_until < now)
            | (
                Run.leased_until.is_(None)
                & (
                    Run.heartbeat_at.is_(None)
                    | (Run.heartbeat_at < stale_cutoff)
                )
            )
            | (Run.heartbeat_at < stale_cutoff)
        )
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
