"""Employee province histories and per-stub snapshots.

Revision ID: d8c2f4a61b90
Revises: 06ae9f5dc58e
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8c2f4a61b90"
down_revision: Union[str, None] = "06ae9f5dc58e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROVINCES = "'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'ON', 'PE', 'SK'"


def _restore_sqlite_company_open_range_index(bind) -> None:
    """Restore the expression index dropped by SQLite batch table rebuilds."""
    if bind.dialect.name != "sqlite":
        return
    op.create_index(
        "uq_company_payroll_jurisdiction_open_range",
        "company_payroll_jurisdictions",
        [sa.text("(1)")],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
    )


def upgrade() -> None:
    op.create_table(
        "employee_payroll_jurisdictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("province_code", sa.String(length=2), nullable=False),
        sa.Column("regulatory_scope", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "country_code = 'CA'", name="ck_employee_payroll_jurisdiction_country"
        ),
        sa.CheckConstraint(
            f"province_code IN ({_PROVINCES})",
            name="ck_employee_payroll_jurisdiction_province",
        ),
        sa.CheckConstraint(
            "regulatory_scope = 'provincially_regulated'",
            name="ck_employee_payroll_jurisdiction_scope",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employee_payroll_jurisdiction_date_range",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id",
            "effective_from",
            name="uq_employee_payroll_jurisdiction_effective_from",
        ),
    )
    op.create_index(
        "uq_employee_payroll_jurisdiction_open_range",
        "employee_payroll_jurisdictions",
        ["employee_id"],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    # Preserve every old company range, exactly, for every employee present at
    # upgrade time. Do not touch pay-run or pay-stub rows or calculated amounts.
    op.execute(
        sa.text(
            "INSERT INTO employee_payroll_jurisdictions "
            "(employee_id, country_code, province_code, regulatory_scope, "
            "effective_from, effective_to, created_at) "
            "SELECT e.id, j.country_code, j.province_code, j.regulatory_scope, "
            "j.effective_from, j.effective_to, j.created_at "
            "FROM employees AS e CROSS JOIN company_payroll_jurisdictions AS j"
        )
    )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "company_payroll_jurisdictions", recreate="always"
        ) as batch_op:
            batch_op.alter_column(
                "province_code",
                existing_type=sa.String(length=2),
                nullable=True,
            )
        _restore_sqlite_company_open_range_index(bind)
    else:
        op.alter_column(
            "company_payroll_jurisdictions",
            "province_code",
            existing_type=sa.String(length=2),
            nullable=True,
        )

    op.add_column(
        "pay_stubs",
        sa.Column("employee_jurisdiction_snapshot", sa.JSON(), nullable=True),
    )


def _ensure_employee_history_is_reconstructible(bind) -> None:
    """Refuse rollback if employee timelines cannot be rebuilt from company history."""
    company_history = [
        tuple(row)
        for row in bind.execute(
            sa.text(
                "SELECT country_code, province_code, regulatory_scope, "
                "effective_from, effective_to "
                "FROM company_payroll_jurisdictions ORDER BY effective_from, id"
            )
        ).all()
    ]
    employee_ids = set(
        bind.execute(sa.text("SELECT id FROM employees ORDER BY id")).scalars().all()
    )
    employee_histories = {employee_id: [] for employee_id in employee_ids}
    employee_rows = bind.execute(
        sa.text(
            "SELECT employee_id, country_code, province_code, regulatory_scope, "
            "effective_from, effective_to "
            "FROM employee_payroll_jurisdictions "
            "ORDER BY employee_id, effective_from, id"
        )
    ).all()
    for row in employee_rows:
        employee_id = row[0]
        if employee_id not in employee_histories:
            raise RuntimeError(
                "Cannot downgrade: employee jurisdiction history has no matching employee."
            )
        employee_histories[employee_id].append(tuple(row[1:]))

    if any(history != company_history for history in employee_histories.values()):
        raise RuntimeError(
            "Cannot downgrade: employee province history differs from legacy "
            "company history; employee-specific data cannot be reconstructed."
        )


def downgrade() -> None:
    bind = op.get_bind()
    null_company_provinces = bind.execute(
        sa.text(
            "SELECT count(*) FROM company_payroll_jurisdictions "
            "WHERE province_code IS NULL"
        )
    ).scalar_one()
    if null_company_provinces:
        raise RuntimeError(
            "Cannot downgrade: country-mode company rows have no province to restore."
        )

    _ensure_employee_history_is_reconstructible(bind)

    op.drop_column("pay_stubs", "employee_jurisdiction_snapshot")
    op.drop_index(
        "uq_employee_payroll_jurisdiction_open_range",
        table_name="employee_payroll_jurisdictions",
    )
    op.drop_table("employee_payroll_jurisdictions")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "company_payroll_jurisdictions", recreate="always"
        ) as batch_op:
            batch_op.alter_column(
                "province_code",
                existing_type=sa.String(length=2),
                nullable=False,
            )
        _restore_sqlite_company_open_range_index(bind)
    else:
        op.alter_column(
            "company_payroll_jurisdictions",
            "province_code",
            existing_type=sa.String(length=2),
            nullable=False,
        )
