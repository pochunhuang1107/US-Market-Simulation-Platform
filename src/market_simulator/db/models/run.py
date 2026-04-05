from datetime import datetime

import uuid
from sqlalchemy import String, Text, ForeignKey, TIMESTAMP, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from market_simulator.db.base import Base
from market_simulator.db.enums import RunStatus, RunType, ExecutorType


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True)
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_versions.id"), nullable=True)

    run_type: Mapped[RunType] = mapped_column(String, nullable=False)
    executor_type: Mapped[ExecutorType] = mapped_column(String, nullable=False)

    status: Mapped[RunStatus] = mapped_column(String, nullable=False)

    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    artifact_manifest_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    artifact_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_daily_tracking_run: Mapped[bool] = mapped_column(Boolean, default=False)

    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="runs")
    strategy = relationship("Strategy", back_populates="runs")
    strategy_version = relationship("StrategyVersion", back_populates="runs")