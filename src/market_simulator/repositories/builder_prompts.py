from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from market_simulator.db.models.builder_prompt_event import BuilderPromptEvent


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def count_builder_prompts_today(db: Session, user_id: str) -> int:
    now = _utc_now()
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    return (
        db.query(func.count(BuilderPromptEvent.id))
        .filter(
            BuilderPromptEvent.user_id == user_id,
            BuilderPromptEvent.created_at >= start_of_day,
            BuilderPromptEvent.created_at < end_of_day,
        )
        .scalar()
        or 0
    )


def create_builder_prompt_event(
    db: Session,
    *,
    user_id: str,
    prompt_chars: int,
    status: str,
    rejection_reason: str | None = None,
) -> BuilderPromptEvent:
    event = BuilderPromptEvent(
        user_id=user_id,
        prompt_chars=prompt_chars,
        status=status,
        rejection_reason=rejection_reason,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event