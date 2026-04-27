"""add max comparison runs to plans

Revision ID: a2b3c4d5e6f7
Revises: 9a1b2c3d4e5f
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("max_comparison_runs", sa.Integer(), nullable=False, server_default="4"),
    )
    op.alter_column("plans", "max_comparison_runs", server_default=None)


def downgrade() -> None:
    op.drop_column("plans", "max_comparison_runs")
