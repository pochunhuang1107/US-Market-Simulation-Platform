import uuid
import hashlib
import json

from sqlalchemy.orm import Session

from market_simulator.db.enums import StrategyStatus
from market_simulator.db.models.run import Run
from market_simulator.db.models.strategy import Strategy, StrategyVersion


def _hash_config(config: dict) -> str:
    normalized = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def create_strategy(db: Session, user_id, name, description, strategy_type):
    strategy = Strategy(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        description=description,
        strategy_type=strategy_type,
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


def create_strategy_version(
    db: Session,
    strategy_id,
    config_json,
    config_hash,
    user_id,
    change_note=None,
):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        return None
    if str(strategy.user_id) != str(user_id):
        return None

    persisted_config_json = dict(config_json)
    if "name" in persisted_config_json and persisted_config_json["name"] != strategy.name:
        persisted_config_json["name"] = strategy.name
    elif "name" not in persisted_config_json:
        persisted_config_json["name"] = strategy.name
    persisted_config_hash = _hash_config(persisted_config_json)

    latest = (
        db.query(StrategyVersion)
        .filter(StrategyVersion.strategy_id == strategy_id)
        .order_by(StrategyVersion.version_number.desc())
        .first()
    )

    next_version = 1 if not latest else latest.version_number + 1

    version = StrategyVersion(
        id=uuid.uuid4(),
        strategy_id=strategy_id,
        version_number=next_version,
        config_json=persisted_config_json,
        config_hash=persisted_config_hash,
        change_note=change_note,
        created_by_user_id=user_id,
    )

    db.add(version)

    strategy.current_version_id = version.id

    db.commit()
    db.refresh(version)

    return version


def list_strategies(db: Session, user_id, include_archived: bool = False):
    statuses = [StrategyStatus.ACTIVE]
    if include_archived:
        statuses.append(StrategyStatus.ARCHIVED)

    return (
        db.query(Strategy)
        .filter(
            Strategy.user_id == user_id,
            Strategy.status.in_(statuses),
        )
        .all()
    )


def get_strategy(db: Session, strategy_id):
    return db.query(Strategy).filter(Strategy.id == strategy_id).first()


def get_strategy_version(db: Session, strategy_version_id):
    return (
        db.query(StrategyVersion)
        .filter(StrategyVersion.id == strategy_version_id)
        .first()
    )


def get_strategy_version_for_user(db: Session, strategy_version_id, user_id):
    return (
        db.query(StrategyVersion)
        .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .filter(
            StrategyVersion.id == strategy_version_id,
            Strategy.user_id == user_id,
        )
        .first()
    )


def set_strategy_version_reference_run(db: Session, *, version_id, run_id, user_id):
    version = (
        db.query(StrategyVersion)
        .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .filter(
            StrategyVersion.id == version_id,
            Strategy.user_id == user_id,
        )
        .first()
    )
    if version is None:
        return None

    run = (
        db.query(Run)
        .filter(
            Run.id == run_id,
            Run.user_id == user_id,
            Run.strategy_id == version.strategy_id,
            Run.strategy_version_id == version.id,
        )
        .first()
    )
    if run is None:
        return None

    version.reference_run_id = run.id
    db.commit()
    db.refresh(version)
    return version


def get_strategy_version_reference_run(db: Session, *, version_id, user_id):
    version = (
        db.query(StrategyVersion)
        .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .filter(
            StrategyVersion.id == version_id,
            Strategy.user_id == user_id,
        )
        .first()
    )
    if version is None or version.reference_run_id is None:
        return None

    return (
        db.query(Run)
        .filter(
            Run.id == version.reference_run_id,
            Run.user_id == user_id,
            Run.strategy_id == version.strategy_id,
            Run.strategy_version_id == version.id,
        )
        .first()
    )


def set_missing_reference_run_from_eligible_success(db: Session, *, version_id, user_id):
    version = (
        db.query(StrategyVersion)
        .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .filter(
            StrategyVersion.id == version_id,
            Strategy.user_id == user_id,
            StrategyVersion.reference_run_id.is_(None),
        )
        .first()
    )
    if version is None:
        return None

    runs = (
        db.query(Run)
        .filter(
            Run.user_id == user_id,
            Run.strategy_id == version.strategy_id,
            Run.strategy_version_id == version.id,
            Run.run_type == "SIMULATION",
            Run.status == "SUCCEEDED",
        )
        .order_by(Run.finished_at.desc().nullslast(), Run.created_at.desc())
        .all()
    )

    for run in runs:
        payload = run.request_payload or {}
        if (
            payload.get("set_as_reference_on_success") is True
            or payload.get("source") == "strategy_version_reference_run"
            or str(payload.get("reference_strategy_version_id")) == str(version.id)
        ):
            version.reference_run_id = run.id
            db.commit()
            db.refresh(version)
            return run

    return None


def get_strategy_for_user(db: Session, strategy_id, user_id):
    return (
        db.query(Strategy)
        .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
        .first()
    )


def update_strategy_status_for_user(db: Session, strategy_id, user_id, status: StrategyStatus):
    strategy = get_strategy_for_user(db, strategy_id, user_id)
    if strategy is None or strategy.status == StrategyStatus.DELETED:
        return None

    strategy.status = status
    db.commit()
    db.refresh(strategy)

    return strategy


def list_strategy_versions(db: Session, strategy_id):
    return (
        db.query(StrategyVersion)
        .filter(StrategyVersion.strategy_id == strategy_id)
        .order_by(StrategyVersion.version_number.desc())
        .all()
    )
