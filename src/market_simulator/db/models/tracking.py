from datetime import datetime, date

import uuid
from sqlalchemy import String, ForeignKey, TIMESTAMP, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

from market_simulator.db.base import Base
from market_simulator.db.enums import TrackingStatus, TrackingMode


class TrackedStrategy(Base):
    __tablename__ = "tracked_strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategies.id"))
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=True)

    status: Mapped[TrackingStatus] = mapped_column(String, nullable=False)
    tracking_mode: Mapped[TrackingMode] = mapped_column(String, nullable=False)

    frequency: Mapped[str] = mapped_column(String, nullable=False)

    next_run_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="tracked_strategies")