"""merge upstream and Canadian payroll migration heads

Revision ID: 06ae9f5dc58e
Revises: c2d3e4f5a6b7, f2c3d4e5f6a7
Create Date: 2026-10-23 02:03:40.857743

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '06ae9f5dc58e'
down_revision: Union[str, None] = ('c2d3e4f5a6b7', 'f2c3d4e5f6a7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
