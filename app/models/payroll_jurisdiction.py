"""Company-level country mode history.

The nullable province column is retained only so legacy values can remain in
place for audit and rollback. New company records leave it NULL; employee
province-of-employment belongs in EmployeePayrollJurisdiction.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)

from app.database import Base


class PayrollJurisdiction(Base):
    __tablename__ = "company_payroll_jurisdictions"
    __table_args__ = (
        UniqueConstraint(
            "effective_from", name="uq_company_payroll_jurisdiction_effective_from"
        ),
        Index(
            "uq_company_payroll_jurisdiction_open_range",
            text("(1)"),
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
        CheckConstraint(
            "country_code = 'CA'", name="ck_company_payroll_jurisdiction_country"
        ),
        # Allows the original audited province values, but NULL is the only
        # value used for new company-level country mode records.
        CheckConstraint(
            "province_code IN ('AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'ON', 'PE', 'SK')",
            name="ck_company_payroll_jurisdiction_province",
        ),
        CheckConstraint(
            "regulatory_scope = 'provincially_regulated'",
            name="ck_company_payroll_jurisdiction_scope",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_company_payroll_jurisdiction_date_range",
        ),
    )

    id = Column(Integer, primary_key=True)
    country_code = Column(String(2), nullable=False, server_default="CA")
    province_code = Column(String(2), nullable=True)
    regulatory_scope = Column(String(32), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
