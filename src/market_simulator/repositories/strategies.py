import uuid
from sqlalchemy.orm import Session
from market_simulator.db.models.strategy import Strategy, StrategyVersion


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


def create_strategy_version(db: Session, strategy_id, config_json, config_hash, user_id):
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
        config_json=config_json,
        config_hash=config_hash,
        created_by_user_id=user_id,
    )

    db.add(version)
    db.commit()
    db.refresh(version)

    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    strategy.current_version_id = version.id
    db.commit()

    return version


def list_strategies(db: Session, user_id):
    return db.query(Strategy).filter(Strategy.user_id == user_id).all()


def get_strategy(db: Session, strategy_id):
    return db.query(Strategy).filter(Strategy.id == strategy_id).first()


def get_strategy_version(db: Session, strategy_version_id):
    return (
        db.query(StrategyVersion)
        .filter(StrategyVersion.id == strategy_version_id)
        .first()
    )