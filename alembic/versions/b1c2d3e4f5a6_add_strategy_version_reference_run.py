"""add strategy version reference run

Revision ID: b1c2d3e4f5a6
Revises: a2b3c4d5e6f7
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "strategy_versions",
        sa.Column("reference_run_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_strategy_versions_reference_run_id_runs",
        "strategy_versions",
        "runs",
        ["reference_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_strategy_versions_reference_run_id_runs",
        "strategy_versions",
        type_="foreignkey",
    )
    op.drop_column("strategy_versions", "reference_run_id")
