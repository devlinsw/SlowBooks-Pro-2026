"""Effective-dated province-of-employment history for one employee."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)

from app.database import Base


class EmployeePayrollJurisdiction(Base):
    __tablename__ = "employee_payroll_jurisdictions"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "effective_from",
            name="uq_employee_payroll_jurisdiction_effective_from",
        ),
        Index(
            "uq_employee_payroll_jurisdiction_open_range",
            "employee_id",
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
        CheckConstraint(
            "country_code = 'CA'", name="ck_employee_payroll_jurisdiction_country"
        ),
        CheckConstraint(
            "province_code IN ('AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'ON', 'PE', 'SK')",
            name="ck_employee_payroll_jurisdiction_province",
        ),
        CheckConstraint(
            "regulatory_scope = 'provincially_regulated'",
            name="ck_employee_payroll_jurisdiction_scope",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employee_payroll_jurisdiction_date_range",
        ),
    )

    id = Column(Integer, primary_key=True)
    employee_id = Column(
        Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    country_code = Column(String(2), nullable=False)
    province_code = Column(String(2), nullable=False)
    regulatory_scope = Column(String(32), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
