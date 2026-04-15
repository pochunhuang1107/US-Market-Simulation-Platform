"""add builder prompt guardrails

Revision ID: 9a1b2c3d4e5f
Revises: 4f5f6d7a8b9c
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "4f5f6d7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("builder_prompt_daily_limit", sa.Integer(), nullable=False, server_default="20"))
    op.add_column("plans", sa.Column("builder_prompt_max_chars", sa.Integer(), nullable=False, server_default="1000"))
    op.add_column("plans", sa.Column("max_backtest_years", sa.Integer(), nullable=False, server_default="5"))

    op.create_table(
        "builder_prompt_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_chars", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("rejection_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.alter_column("plans", "builder_prompt_daily_limit", server_default=None)
    op.alter_column("plans", "builder_prompt_max_chars", server_default=None)
    op.alter_column("plans", "max_backtest_years", server_default=None)


def downgrade() -> None:
    op.drop_table("builder_prompt_events")
    op.drop_column("plans", "max_backtest_years")
    op.drop_column("plans", "builder_prompt_max_chars")
    op.drop_column("plans", "builder_prompt_daily_limit")