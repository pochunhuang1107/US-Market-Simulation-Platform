"""add advanced rotation entitlements

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("allow_rotation_templates", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "plans",
        sa.Column("allow_custom_rotation", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "plans",
        sa.Column("allow_rotation_edit", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "plans",
        sa.Column("allow_advanced_builder", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.execute(
        """
        UPDATE plans
        SET allow_rotation_templates = TRUE
        WHERE code IN ('FREE', 'PRO', 'RESEARCH', 'BETA_TESTER')
        """
    )
    op.execute(
        """
        UPDATE plans
        SET
            allow_custom_rotation = TRUE,
            allow_rotation_edit = TRUE,
            allow_advanced_builder = TRUE
        WHERE code IN ('PRO', 'RESEARCH', 'BETA_TESTER')
        """
    )

    for column_name in (
        "allow_rotation_templates",
        "allow_custom_rotation",
        "allow_rotation_edit",
        "allow_advanced_builder",
    ):
        op.alter_column("plans", column_name, server_default=None)


def downgrade() -> None:
    op.drop_column("plans", "allow_advanced_builder")
    op.drop_column("plans", "allow_rotation_edit")
    op.drop_column("plans", "allow_custom_rotation")
    op.drop_column("plans", "allow_rotation_templates")
