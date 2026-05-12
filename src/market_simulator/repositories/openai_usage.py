from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from market_simulator.db.models.openai_usage_event import OpenAIUsageEvent


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def count_openai_usage_today(db: Session, user_id: str) -> int:
    now = _utc_now()
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    return (
        db.query(func.count(OpenAIUsageEvent.id))
        .filter(
            OpenAIUsageEvent.user_id == user_id,
            OpenAIUsageEvent.provider == "openai",
            OpenAIUsageEvent.created_at >= start_of_day,
            OpenAIUsageEvent.created_at < end_of_day,
        )
        .scalar()
        or 0
    )


def create_openai_usage_event(
    db: Session,
    *,
    user_id: str,
    provider: str,
    mode: str,
    model: str | None,
    prompt_chars: int,
    response_chars: int | None,
    status: str,
    duration_ms: int | None,
    fallback_used: bool,
    response_type: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
) -> OpenAIUsageEvent:
    event = OpenAIUsageEvent(
        user_id=user_id,
        provider=provider,
        mode=mode,
        model=model,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        status=status,
        duration_ms=duration_ms,
        fallback_used=fallback_used,
        response_type=response_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=(
            Decimal(str(estimated_cost_usd))
            if estimated_cost_usd is not None
            else None
        ),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
