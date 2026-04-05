from datetime import datetime

import uuid
from sqlalchemy import String, Text, ForeignKey, TIMESTAMP, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from market_simulator.db.base import Base
from market_simulator.db.enums import (
    ArtifactStorageType,
    ExecutorType,
    RunStatus,
    RunType,
)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategies.id"),
        nullable=True,
    )
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_versions.id"),
        nullable=True,
    )

    run_type: Mapped[RunType] = mapped_column(String, nullable=False)
    executor_type: Mapped[ExecutorType] = mapped_column(String, nullable=False)

    status: Mapped[RunStatus] = mapped_column(String, nullable=False)

    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    artifact_manifest_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    artifact_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_storage_type: Mapped[ArtifactStorageType] = mapped_column(
        String,
        nullable=False,
        default=ArtifactStorageType.LOCAL,
    )
    artifact_root_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_daily_tracking_run: Mapped[bool] = mapped_column(Boolean, default=False)

    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id"),
        nullable=True,
    )

    queued_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)

    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("User", back_populates="runs")
    strategy = relationship("Strategy", back_populates="runs")
    strategy_version = relationship("StrategyVersion", back_populates="runs")