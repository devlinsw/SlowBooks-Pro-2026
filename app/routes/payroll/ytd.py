from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.payroll import (
    PayRun,
    PayStub,
    PayRunStatus,
    PayRunType,
)
from app.services.payroll_jurisdiction_service import (
    PayrollJurisdictionAmbiguous,
    PayrollJurisdictionPeriodBoundary,
    is_us_payroll_period,
    lock_company_payroll_jurisdiction,
)


# ---------------------------------------------------------------------------
# Year-to-date helpers — fixes Bug 1 (YTD was never threaded into the calc, so
# the Social Security wage-base cap could never fire).
# ---------------------------------------------------------------------------
def _ytd_stubs(
    db: Session, employee_id: int, year: int, before: date | None = None
):
    q = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .filter(
            PayStub.employee_id == employee_id,
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= date(year, 1, 1),
            PayRun.pay_date <= date(year, 12, 31),
        )
    )
    if before is not None:
        q = q.filter(PayRun.pay_date < before)
    return q.all()


def _reject_orphan_ytd_stubs(db: Session, employee_id: int) -> None:
    """Fail closed when any employee pay stub has no parent run."""
    missing_parent = (
        db.query(PayStub.id)
        .outerjoin(PayRun, PayStub.pay_run_id == PayRun.id)
        .filter(PayStub.employee_id == employee_id, PayRun.id.is_(None))
        .first()
    )
    if missing_parent is not None:
        raise HTTPException(
            status_code=409,
            detail="Payroll YTD history is ambiguous; a stub has no parent pay run.",
        )


def _validate_us_ytd_contributor(db: Session, run: PayRun | None) -> None:
    """Reject a missing, Canadian, boundary, or ambiguous source run."""
    if run is None:
        raise HTTPException(
            status_code=409,
            detail="Payroll YTD history is ambiguous; a stub has no parent pay run.",
        )
    try:
        safe = is_us_payroll_period(
            db,
            run.period_start,
            run.period_end,
            jurisdiction_snapshot=run.jurisdiction_snapshot,
        )
    except PayrollJurisdictionPeriodBoundary as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PayrollJurisdictionAmbiguous as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Payroll jurisdiction status is unavailable; YTD inputs are blocked.",
        ) from exc
    if not safe:
        raise HTTPException(
            status_code=422,
            detail="U.S. payroll YTD inputs are unavailable for Canadian periods.",
        )


def _validated_ytd_stubs(
    db: Session, employee_id: int, year: int, before: date | None = None
) -> list[PayStub]:
    """Load and validate one locked YTD contributor snapshot for an operation."""
    try:
        lock_company_payroll_jurisdiction(db)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Payroll jurisdiction status is unavailable; YTD inputs are blocked.",
        ) from exc

    try:
        _reject_orphan_ytd_stubs(db, employee_id)
        stubs = _ytd_stubs(db, employee_id, year, before)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Payroll YTD history is unavailable; payroll inputs are blocked.",
        ) from exc

    for stub in stubs:
        try:
            run = stub.pay_run
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Payroll YTD history is unavailable; payroll inputs are blocked.",
            ) from exc
        _validate_us_ytd_contributor(db, run)
    return stubs


def employee_ytd(
    db: Session,
    employee_id: int,
    year: int,
    before: date | None = None,
    stubs: list[PayStub] | None = None,
) -> dict:
    """Aggregate an employee's pay-stub figures for a calendar year."""
    totals = {
        "gross": Decimal("0"),
        "federal": Decimal("0"),
        "state": Decimal("0"),
        "state_other": Decimal("0"),
        "ss": Decimal("0"),
        "medicare": Decimal("0"),
        "pretax_deductions": Decimal("0"),
        "net": Decimal("0"),
    }
    for s in (
        _ytd_stubs(db, employee_id, year, before) if stubs is None else stubs
    ):
        totals["gross"] += s.gross_pay or 0
        totals["federal"] += s.federal_tax or 0
        totals["state"] += s.state_tax or 0
        totals["state_other"] += s.state_other_employee or 0
        totals["ss"] += s.ss_tax or 0
        totals["medicare"] += s.medicare_tax or 0
        totals["pretax_deductions"] += s.pretax_deductions or 0
        totals["net"] += s.net_pay or 0
    return totals


def _ytd_supplemental(
    db: Session,
    employee_id: int,
    year: int,
    before: date = None,
    stubs: list[PayStub] | None = None,
) -> Decimal:
    """YTD supplemental wages — gross pay from BONUS-type runs this year.

    Drives the $1M/37% supplemental withholding tier. Approximation: bonuses
    paid as supplemental stubs inside a REGULAR run aren't distinguishable
    after the fact (PayStub has no supplemental flag), so only BONUS runs
    count — the path bonuses are actually processed through.
    """
    total = Decimal("0")
    for s in (_ytd_stubs(db, employee_id, year, before) if stubs is None else stubs):
        if s.pay_run and s.pay_run.run_type == PayRunType.BONUS:
            total += s.gross_pay or 0
    return total
