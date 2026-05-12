from datetime import datetime

import uuid
from sqlalchemy import String, Boolean, Numeric, Integer, ForeignKey, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

from market_simulator.db.base import Base
from market_simulator.db.enums import UserStatus, SubscriptionStatus


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[UserStatus] = mapped_column(String, default=UserStatus.ACTIVE, nullable=False)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    subscriptions = relationship("UserPlanSubscription", back_populates="user")
    external_identities = relationship(
        "UserExternalIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    strategies = relationship("Strategy", back_populates="user")
    runs = relationship("Run", back_populates="user")
    tracked_strategies = relationship("TrackedStrategy", back_populates="user")
    builder_prompt_events = relationship("BuilderPromptEvent", back_populates="user")
    openai_usage_events = relationship("OpenAIUsageEvent", back_populates="user")


class UserExternalIdentity(Base):
    __tablename__ = "user_external_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "subject",
            name="uq_user_external_identities_provider_subject",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    email_at_link_time: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("User", back_populates="external_identities")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    monthly_price_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    daily_free_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    max_saved_strategies: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tracked_strategies: Mapped[int] = mapped_column(Integer, nullable=False)

    builder_prompt_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    builder_prompt_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    max_backtest_years: Mapped[int] = mapped_column(Integer, nullable=False)
    max_comparison_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    allow_portfolio_runs: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_comparison_runs: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_parameter_sweeps: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_ai_builder: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_strategy_history: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_rotation_templates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_custom_rotation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_rotation_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_advanced_builder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    subscriptions = relationship("UserPlanSubscription", back_populates="plan")


class UserPlanSubscription(Base):
    __tablename__ = "user_plan_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"))

    status: Mapped[SubscriptionStatus] = mapped_column(String, nullable=False)

    starts_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False)

    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
