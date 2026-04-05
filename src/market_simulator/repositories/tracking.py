import uuid
from sqlalchemy.orm import Session
from market_simulator.db.models.tracking import TrackedStrategy


def create_tracked_strategy(db: Session, user_id, strategy_id, strategy_version_id, tracking_mode):
    tracked = TrackedStrategy(
        id=uuid.uuid4(),
        user_id=user_id,
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        status="ACTIVE",
        tracking_mode=tracking_mode,
        frequency="DAILY",
    )
    db.add(tracked)
    db.commit()
    db.refresh(tracked)
    return tracked


def list_tracked_strategies(db: Session, user_id):
    return db.query(TrackedStrategy).filter(TrackedStrategy.user_id == user_id).all()