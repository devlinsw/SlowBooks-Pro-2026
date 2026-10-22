"""Add copied Canadian jurisdiction data to pay runs.

Revision ID: f2c3d4e5f6a7
Revises: f1b2c3d4e5f6
Create Date: 2026-10-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2c3d4e5f6a7"
down_revision: Union[str, None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pay_runs",
        sa.Column("jurisdiction_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pay_runs", "jurisdiction_snapshot")
