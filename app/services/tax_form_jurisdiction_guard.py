"""Fail-closed jurisdiction validation for U.S. payroll tax-form outputs.

The lock is held by the caller's SQLAlchemy transaction through calculation,
hashing, and rendering so the selected contributors cannot change mid-output.
"""

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from app.models.payroll import PayRun, PayRunStatus, PayStub
from app.services.payroll_jurisdiction_service import (
    PayrollJurisdictionAmbiguous,
    PayrollJurisdictionLockUnsupported,
    PayrollJurisdictionPeriodBoundary,
    is_us_payroll_period,
    lock_company_payroll_jurisdiction,
    resolve_company_payroll_jurisdiction_for_period,
)

_UNAVAILABLE_DETAIL = "Payroll jurisdiction history is temporarily unavailable."
_UNSUPPORTED_DETAIL = (
    "U.S. payroll forms are available only for wholly U.S. periods; "
    "Canadian forms are not implemented."
)
_AMBIGUOUS_DETAIL = (
    "Payroll jurisdiction or contributor history is ambiguous; "
    "U.S. payroll forms cannot be generated."
)


def calendar_year_bounds(year: int) -> tuple[date, date]:
    """Inclusive calendar-year interval used by annual U.S. tax forms."""
    return date(year, 1, 1), date(year, 12, 31)


def calendar_quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    """Inclusive calendar-quarter interval used by quarterly forms."""
    if quarter not in (1, 2, 3, 4):
        raise ValueError("quarter must be 1-4")
    month = (quarter - 1) * 3 + 1
    start = date(year, month, 1)
    if quarter == 4:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 3, 1) - timedelta(days=1)
    return start, end


def lock_tax_form_jurisdiction(db) -> None:
    """Acquire the shared lock before any tax-form-specific database read."""
    try:
        lock_company_payroll_jurisdiction(db)
    except (PayrollJurisdictionLockUnsupported, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from exc


def _check_period(db, start: date, end: date) -> None:
    try:
        country = resolve_company_payroll_jurisdiction_for_period(db, start, end)
    except PayrollJurisdictionPeriodBoundary as exc:
        raise HTTPException(status_code=422, detail=_UNSUPPORTED_DETAIL) from exc
    except PayrollJurisdictionAmbiguous as exc:
        raise HTTPException(status_code=409, detail=_AMBIGUOUS_DETAIL) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from exc
    if country is not None:
        raise HTTPException(status_code=422, detail=_UNSUPPORTED_DETAIL)


def load_us_tax_form_contributors(
    db,
    period_start: date,
    period_end: date,
    *,
    contributor_start: date | None = None,
    contributor_end: date | None = None,
    employee_id: int | None = None,
) -> list[PayStub]:
    """Lock jurisdiction history and return the exact validated stub set.

    ``period_*`` is the requested return period. The contributor interval may
    be wider (Form 941 uses year-to-date stubs through quarter end). All date
    boundaries are inclusive. Every selected run's complete pay period and
    both stored jurisdiction snapshots are independently checked.
    """
    lock_tax_form_jurisdiction(db)

    source_start = contributor_start or period_start
    source_end = contributor_end or period_end
    _check_period(db, period_start, period_end)
    if (source_start, source_end) != (period_start, period_end):
        _check_period(db, source_start, source_end)

    query = (
        db.query(PayStub)
        .outerjoin(PayRun, PayStub.pay_run_id == PayRun.id)
        .options(
            joinedload(PayStub.pay_run),
            joinedload(PayStub.employee),
            selectinload(PayStub.benefits),
        )
        .filter(
            or_(
                PayRun.id.is_(None),
                and_(
                    PayRun.status == PayRunStatus.PROCESSED,
                    PayRun.pay_date >= source_start,
                    PayRun.pay_date <= source_end,
                ),
            )
        )
    )
    if employee_id is not None:
        query = query.filter(PayStub.employee_id == employee_id)

    try:
        stubs = query.all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from exc
    for stub in stubs:
        run = stub.pay_run
        if run is None or stub.employee is None:
            raise HTTPException(status_code=409, detail=_AMBIGUOUS_DETAIL)
        try:
            safe = is_us_payroll_period(
                db,
                run.period_start,
                run.period_end,
                jurisdiction_snapshot=run.jurisdiction_snapshot,
            )
        except PayrollJurisdictionPeriodBoundary as exc:
            raise HTTPException(status_code=422, detail=_UNSUPPORTED_DETAIL) from exc
        except PayrollJurisdictionAmbiguous as exc:
            raise HTTPException(status_code=409, detail=_AMBIGUOUS_DETAIL) from exc
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from exc
        if not safe or stub.employee_jurisdiction_snapshot is not None:
            raise HTTPException(status_code=422, detail=_UNSUPPORTED_DETAIL)
    return stubs


def annual_us_contributors(db, year: int, *, employee_id: int | None = None):
    start, end = calendar_year_bounds(year)
    return load_us_tax_form_contributors(
        db, start, end, employee_id=employee_id
    )


def quarterly_us_contributors(db, year: int, quarter: int):
    start, end = calendar_quarter_bounds(year, quarter)
    return load_us_tax_form_contributors(db, start, end)


def form_941_us_contributors(db, year: int, quarter: int):
    quarter_start, quarter_end = calendar_quarter_bounds(year, quarter)
    ytd_start = date(year, 1, 1)
    return load_us_tax_form_contributors(
        db,
        quarter_start,
        quarter_end,
        contributor_start=ytd_start,
        contributor_end=quarter_end,
    )


def map_audit_form_contributors(db, parsed: dict) -> list[PayStub]:
    """Load safe contributors for a parsed audit key during a recheck."""
    year = parsed["year"]
    if "quarter" in parsed:
        return form_941_us_contributors(db, year, parsed["quarter"])
    return annual_us_contributors(
        db, year, employee_id=parsed.get("employee_id")
    )
