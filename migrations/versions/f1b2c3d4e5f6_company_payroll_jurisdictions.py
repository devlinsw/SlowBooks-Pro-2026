"""company-level, effective-dated payroll jurisdiction

Revision ID: f1b2c3d4e5f6
Revises: e8f9a0b1c2d3
Create Date: 2026-10-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_payroll_jurisdictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "country_code", sa.String(length=2), server_default="CA", nullable=False
        ),
        sa.Column("province_code", sa.String(length=2), nullable=False),
        sa.Column(
            "regulatory_scope",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "country_code = 'CA'", name="ck_company_payroll_jurisdiction_country"
        ),
        sa.CheckConstraint(
            "province_code IN ('AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'ON', 'PE', 'SK')",
            name="ck_company_payroll_jurisdiction_province",
        ),
        sa.CheckConstraint(
            "regulatory_scope = 'provincially_regulated'",
            name="ck_company_payroll_jurisdiction_scope",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_company_payroll_jurisdiction_date_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "effective_from", name="uq_company_payroll_jurisdiction_effective_from"
        ),
    )
    # One open-ended timeline head, enforced across concurrent writes.
    op.create_index(
        "uq_company_payroll_jurisdiction_open_range",
        "company_payroll_jurisdictions",
        [sa.text("(1)")],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
        postgresql_where=sa.text("effective_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_company_payroll_jurisdiction_open_range",
        table_name="company_payroll_jurisdictions",
    )
    op.drop_table("company_payroll_jurisdictions")
