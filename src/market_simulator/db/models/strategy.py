from datetime import datetime

import uuid
from sqlalchemy import String, Text, ForeignKey, Integer, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from market_simulator.db.base import Base
from market_simulator.db.enums import StrategyStatus, StrategyType


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    strategy_type: Mapped[StrategyType] = mapped_column(String, nullable=False)
    visibility: Mapped[str] = mapped_column(String, default="PRIVATE", nullable=False)
    status: Mapped[StrategyStatus] = mapped_column(String, default=StrategyStatus.ACTIVE, nullable=False)

    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="strategies")
    versions = relationship("StrategyVersion", back_populates="strategy")
    runs = relationship("Run", back_populates="strategy")


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"

    __table_args__ = (
        UniqueConstraint("strategy_id", "version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategies.id"))

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String, nullable=False)

    change_note: Mapped[str | None] = mapped_column(String, nullable=True)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    strategy = relationship("Strategy", back_populates="versions")
    creator = relationship("User")
    runs = relationship("Run", back_populates="strategy_version")