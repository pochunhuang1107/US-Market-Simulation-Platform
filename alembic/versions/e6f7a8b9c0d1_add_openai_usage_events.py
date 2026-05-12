"""add openai usage events

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openai_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt_chars", sa.Integer(), nullable=False),
        sa.Column("response_chars", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("response_type", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_openai_usage_events_user_created_at",
        "openai_usage_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_openai_usage_events_user_created_at", table_name="openai_usage_events")
    op.drop_table("openai_usage_events")
