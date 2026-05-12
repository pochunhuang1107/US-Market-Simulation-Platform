from datetime import datetime

import uuid
from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from market_simulator.db.base import Base


class OpenAIUsageEvent(Base):
    __tablename__ = "openai_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    response_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_type: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="openai_usage_events")
