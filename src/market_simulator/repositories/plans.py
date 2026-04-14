from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from market_simulator.db.models.run import Run
from market_simulator.db.models.strategy import Strategy
from market_simulator.db.models.tracking import TrackedStrategy
from market_simulator.db.models.user import Plan, UserPlanSubscription


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_active_subscription_with_plan(db: Session, user_id: str):
    now = utc_now()

    return (
        db.query(UserPlanSubscription, Plan)
        .join(Plan, Plan.id == UserPlanSubscription.plan_id)
        .filter(
            UserPlanSubscription.user_id == user_id,
            UserPlanSubscription.status == "ACTIVE",
            Plan.is_active.is_(True),
            UserPlanSubscription.starts_at <= now,
            (
                (UserPlanSubscription.ends_at.is_(None))
                | (UserPlanSubscription.ends_at > now)
            ),
        )
        .order_by(UserPlanSubscription.starts_at.desc())
        .first()
    )


def count_saved_strategies(db: Session, user_id: str) -> int:
    return (
        db.query(func.count(Strategy.id))
        .filter(
            Strategy.user_id == user_id,
            Strategy.status != "DELETED",
        )
        .scalar()
        or 0
    )


def count_tracked_strategies(db: Session, user_id: str) -> int:
    return (
        db.query(func.count(TrackedStrategy.id))
        .filter(
            TrackedStrategy.user_id == user_id,
        )
        .scalar()
        or 0
    )


def count_runs_created_today(db: Session, user_id: str) -> int:
    now = utc_now()
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    return (
        db.query(func.count(Run.id))
        .filter(
            Run.user_id == user_id,
            Run.created_at >= start_of_day,
            Run.created_at < end_of_day,
        )
        .scalar()
        or 0
    )