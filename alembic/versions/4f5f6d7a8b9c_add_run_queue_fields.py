"""add run queue fields

Revision ID: 4f5f6d7a8b9c
Revises: e75ad53e9bf2
Create Date: 2026-04-05 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4f5f6d7a8b9c"
down_revision: Union[str, Sequence[str], None] = "e75ad53e9bf2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("queued_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("heartbeat_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "runs",
        sa.Column("worker_id", sa.String(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runs",
        sa.Column("progress_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("leased_until", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("artifact_storage_type", sa.String(), nullable=False, server_default="LOCAL"),
    )
    op.add_column(
        "runs",
        sa.Column("artifact_root_uri", sa.Text(), nullable=True),
    )

    op.create_index("ix_runs_status", "runs", ["status"], unique=False)
    op.create_index("ix_runs_user_id_created_at", "runs", ["user_id", "created_at"], unique=False)
    op.create_index("ix_runs_status_created_at", "runs", ["status", "created_at"], unique=False)
    op.create_index("ix_runs_status_leased_until", "runs", ["status", "leased_until"], unique=False)

    op.alter_column("runs", "attempt_count", server_default=None)
    op.alter_column("runs", "max_attempts", server_default=None)
    op.alter_column("runs", "progress_pct", server_default=None)
    op.alter_column("runs", "artifact_storage_type", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_runs_status_leased_until", table_name="runs")
    op.drop_index("ix_runs_status_created_at", table_name="runs")
    op.drop_index("ix_runs_user_id_created_at", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")

    op.drop_column("runs", "artifact_root_uri")
    op.drop_column("runs", "artifact_storage_type")
    op.drop_column("runs", "leased_until")
    op.drop_column("runs", "progress_message")
    op.drop_column("runs", "progress_pct")
    op.drop_column("runs", "worker_id")
    op.drop_column("runs", "max_attempts")
    op.drop_column("runs", "attempt_count")
    op.drop_column("runs", "heartbeat_at")
    op.drop_column("runs", "queued_at")