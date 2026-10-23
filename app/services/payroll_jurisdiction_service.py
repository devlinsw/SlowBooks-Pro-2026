"""Validation and effective-dated payroll-jurisdiction history services.

Company records represent only the Canadian country boundary. Province of
employment is maintained independently for each employee. These services do
not calculate payroll or modify existing pay-run/pay-stub snapshots.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError

from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction
from app.models.payroll import Employee, PayRun, PayRunStatus, PayStub
from app.models.payroll_jurisdiction import PayrollJurisdiction

SUPPORTED_COUNTRY = "CA"
# None is the company-level country-mode value accepted by older route guards;
# employee province validation below rejects it explicitly.
SUPPORTED_PROVINCES = frozenset({"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK", None})
SUPPORTED_SCOPE = "provincially_regulated"
MIN_EFFECTIVE_DATE = date(2026, 1, 1)
_GUARD_TRANSACTION_INFO_KEY = "payroll_jurisdiction_guard_transaction"


class PayrollJurisdictionLockUnsupported(RuntimeError):
    """The database dialect has no supported transaction lock implementation."""


def lock_company_payroll_jurisdiction(db):
    """Acquire both jurisdiction table locks in stable order for this transaction.

    SQLite obtains its writer lock by issuing no-op updates on both tables;
    PostgreSQL takes transaction-scoped locks in the same company-then-employee
    order. Unsupported dialects or lock errors fail closed.
    """
    transaction = db.get_transaction()
    if transaction is not None and db.info.get(_GUARD_TRANSACTION_INFO_KEY) is transaction:
        return

    try:
        dialect = db.get_bind().dialect.name
        if dialect == "sqlite":
            db.execute(
                text(
                    "UPDATE company_payroll_jurisdictions "
                    "SET effective_from = effective_from WHERE 1 = 0"
                )
            )
            db.execute(
                text(
                    "UPDATE employee_payroll_jurisdictions "
                    "SET effective_from = effective_from WHERE 1 = 0"
                )
            )
        elif dialect == "postgresql":
            db.execute(
                text(
                    "LOCK TABLE company_payroll_jurisdictions, "
                    "employee_payroll_jurisdictions IN SHARE ROW EXCLUSIVE MODE"
                )
            )
        else:
            raise PayrollJurisdictionLockUnsupported(
                f"Payroll jurisdiction guard locking is unsupported for {dialect}."
            )
    except Exception:
        db.rollback()
        db.info.pop(_GUARD_TRANSACTION_INFO_KEY, None)
        raise

    db.info[_GUARD_TRANSACTION_INFO_KEY] = db.get_transaction()


class PayrollJurisdictionError(ValueError):
    """A jurisdiction setting does not satisfy input validation."""


class PayrollJurisdictionConflict(PayrollJurisdictionError):
    """A setting conflicts with an existing effective-dated timeline."""


class PayrollJurisdictionAmbiguous(PayrollJurisdictionConflict):
    """Stored effective ranges overlap, have gaps, or are not fully resolvable."""


class PayrollJurisdictionPeriodBoundary(PayrollJurisdictionConflict):
    """The payroll period spans the U.S.-Canadian country-mode boundary."""


class EmployeePayrollJurisdictionConflict(PayrollJurisdictionConflict):
    """An employee province change conflicts with history or processed payroll."""


class EmployeePayrollJurisdictionAmbiguous(PayrollJurisdictionAmbiguous):
    """An employee province cannot be resolved for the requested period."""


@dataclass(frozen=True)
class CompanyCountryMode:
    id: int
    country_code: str
    province_code: None
    regulatory_scope: str
    effective_from: date
    effective_to: date | None


def _ordered_history(db, *, lock=False):
    query = db.query(PayrollJurisdiction).order_by(
        PayrollJurisdiction.effective_from.asc(), PayrollJurisdiction.id.asc()
    )
    if lock:
        query = query.with_for_update()
    history = query.all()
    if lock and history:
        history = query.populate_existing().all()
    return history


def _validate_history(history):
    """Require company history ranges to be ordered and contiguous."""
    for index, item in enumerate(history):
        if item.effective_to is not None and item.effective_to < item.effective_from:
            raise PayrollJurisdictionAmbiguous(
                "Stored payroll jurisdiction history has an invalid effective range."
            )
        if index == 0:
            continue
        previous = history[index - 1]
        if previous.effective_to is None or previous.effective_to >= item.effective_from:
            raise PayrollJurisdictionAmbiguous(
                "Stored payroll jurisdiction history has overlapping or ambiguous ranges."
            )
        if previous.effective_to + timedelta(days=1) != item.effective_from:
            raise PayrollJurisdictionAmbiguous(
                "Stored payroll jurisdiction history has an uncovered date range."
            )
    if history and history[-1].effective_to is not None:
        raise PayrollJurisdictionAmbiguous(
            "Stored payroll jurisdiction history has no open-ended current range."
        )


def resolve_company_payroll_jurisdiction(db, as_of: date, *, lock=False):
    """Return the Canadian country mode effective on a date, or ``None``.

    Legacy company province values remain stored for audit and migration
    rollback, but are deliberately masked from all new readers and snapshots.
    """
    history = _ordered_history(db, lock=lock)
    _validate_history(history)
    matches = [
        item
        for item in history
        if item.effective_from <= as_of
        and (item.effective_to is None or as_of <= item.effective_to)
    ]
    if len(matches) > 1:
        raise PayrollJurisdictionAmbiguous(
            "More than one payroll jurisdiction is effective on this date."
        )
    if not matches:
        return None
    record = matches[0]
    return CompanyCountryMode(
        id=record.id,
        country_code=record.country_code,
        province_code=None,
        regulatory_scope=record.regulatory_scope,
        effective_from=record.effective_from,
        effective_to=record.effective_to,
    )


def resolve_company_payroll_jurisdiction_for_period(
    db, period_start: date, period_end: date, *, lock=False
):
    """Resolve Canadian mode against the complete inclusive payroll period."""
    if (
        not isinstance(period_start, date)
        or not isinstance(period_end, date)
        or period_start > period_end
    ):
        raise PayrollJurisdictionAmbiguous(
            "The payroll period has an invalid effective date range."
        )

    history = _ordered_history(db, lock=lock)
    _validate_history(history)
    if not history:
        return None

    first_effective_from = history[0].effective_from
    if period_start < first_effective_from <= period_end:
        raise PayrollJurisdictionPeriodBoundary(
            "Payroll periods that cross the U.S.-Canadian country-mode boundary "
            "are not supported."
        )

    overlaps = [
        record
        for record in history
        if record.effective_from <= period_end
        and (record.effective_to is None or period_start <= record.effective_to)
    ]
    if not overlaps:
        return None

    record = next(
        (
            item
            for item in history
            if item.effective_from <= period_start
            and (item.effective_to is None or period_start <= item.effective_to)
        ),
        None,
    )
    if record is None:
        # A valid history cannot leave a gap; reaching this branch means stored
        # values were malformed or the period overlaps only part of a range.
        raise PayrollJurisdictionAmbiguous(
            "The payroll period does not resolve to one company country mode."
        )
    return CompanyCountryMode(
        id=record.id,
        country_code=record.country_code,
        province_code=None,
        regulatory_scope=record.regulatory_scope,
        effective_from=record.effective_from,
        effective_to=record.effective_to,
    )


def is_us_payroll_period(
    db,
    period_start: date,
    period_end: date,
    *,
    jurisdiction_snapshot=None,
):
    """Whether a complete period can be exposed through U.S. payroll outputs.

    Period boundaries and ambiguous history propagate as fail-closed errors.
    A stored jurisdiction snapshot also prevents old rows from being exposed as
    U.S. data even if the live company history was later removed or altered.
    """
    jurisdiction = resolve_company_payroll_jurisdiction_for_period(
        db, period_start, period_end
    )
    return jurisdiction is None and jurisdiction_snapshot is None


def list_company_payroll_jurisdictions(db):
    history = _ordered_history(db)
    _validate_history(history)
    return history


def serialize_company_payroll_jurisdiction(record):
    """Serialize country mode without presenting an audited legacy province."""
    return {
        "country_code": record.country_code,
        "effective_from": record.effective_from.isoformat(),
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
    }


def _is_expected_timeline_unique_conflict(exc, *, employee=False):
    if employee:
        expected_constraints = {
            "uq_employee_payroll_jurisdiction_effective_from",
            "uq_employee_payroll_jurisdiction_open_range",
        }
        table_prefix = "employee_payroll_jurisdictions"
    else:
        expected_constraints = {
            "uq_company_payroll_jurisdiction_effective_from",
            "uq_company_payroll_jurisdiction_open_range",
        }
        table_prefix = "company_payroll_jurisdictions"
    original = exc.orig
    constraint_name = getattr(getattr(original, "diag", None), "constraint_name", None)
    if constraint_name in expected_constraints:
        return True
    if isinstance(original, sqlite3.IntegrityError):
        message = str(original)
        return (
            f"UNIQUE constraint failed: {table_prefix}.effective_from" in message
            or f"UNIQUE constraint failed: {table_prefix}.employee_id, "
            f"{table_prefix}.effective_from" in message
            or f"UNIQUE constraint failed: index 'uq_{table_prefix}_open_range'"
            in message
        )
    return False


def add_company_payroll_jurisdiction(db, *, country_code: str, effective_from: date):
    """Enable Canadian country mode prospectively, without selecting a province."""
    if country_code != SUPPORTED_COUNTRY:
        raise PayrollJurisdictionError("country_code must be CA for this setting.")
    if effective_from < MIN_EFFECTIVE_DATE:
        raise PayrollJurisdictionError("effective_from must be 2026-01-01 or later.")

    lock_company_payroll_jurisdiction(db)
    processed_run = (
        db.query(PayRun.id)
        .filter(
            PayRun.status == PayRunStatus.PROCESSED,
            or_(
                PayRun.pay_date >= effective_from,
                PayRun.period_end >= effective_from,
            ),
        )
        .first()
    )
    if processed_run is not None:
        raise PayrollJurisdictionConflict(
            "A processed pay run exists on or after the proposed effective date."
        )

    history = _ordered_history(db, lock=True)
    _validate_history(history)
    today = date.today()
    if history:
        raise PayrollJurisdictionConflict(
            "Canadian country mode is already configured or scheduled."
        )
    if effective_from < today:
        raise PayrollJurisdictionError(
            "The initial payroll jurisdiction must be effective today or prospectively."
        )

    record = PayrollJurisdiction(
        country_code=country_code,
        province_code=None,
        regulatory_scope=SUPPORTED_SCOPE,
        effective_from=effective_from,
        effective_to=None,
    )
    db.add(record)
    response = serialize_company_payroll_jurisdiction(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_expected_timeline_unique_conflict(exc):
            raise PayrollJurisdictionConflict(
                "Canadian country mode is already configured or scheduled."
            ) from exc
        raise
    return response


def _ordered_employee_history(db, employee_id: int, *, lock=False):
    query = (
        db.query(EmployeePayrollJurisdiction)
        .filter(EmployeePayrollJurisdiction.employee_id == employee_id)
        .order_by(
            EmployeePayrollJurisdiction.effective_from.asc(),
            EmployeePayrollJurisdiction.id.asc(),
        )
    )
    if lock:
        query = query.with_for_update()
    history = query.all()
    if lock and history:
        history = query.populate_existing().all()
    return history


def _validate_employee_history(history):
    """Validate a complete per-employee timeline, including gaps and tail."""
    for index, item in enumerate(history):
        if (
            item.country_code != SUPPORTED_COUNTRY
            or item.province_code is None
            or item.province_code not in SUPPORTED_PROVINCES
            or item.regulatory_scope != SUPPORTED_SCOPE
        ):
            raise EmployeePayrollJurisdictionAmbiguous(
                "Stored employee payroll jurisdiction has unsupported values."
            )
        if item.effective_to is not None and item.effective_to < item.effective_from:
            raise EmployeePayrollJurisdictionAmbiguous(
                "Stored employee payroll jurisdiction has an invalid effective range."
            )
        if index == 0:
            continue
        previous = history[index - 1]
        if previous.effective_to is None or previous.effective_to >= item.effective_from:
            raise EmployeePayrollJurisdictionAmbiguous(
                "Stored employee payroll jurisdiction history has overlapping ranges."
            )
        if previous.effective_to + timedelta(days=1) != item.effective_from:
            raise EmployeePayrollJurisdictionAmbiguous(
                "Stored employee payroll jurisdiction history has an uncovered date range."
            )
    if history and history[-1].effective_to is not None:
        raise EmployeePayrollJurisdictionAmbiguous(
            "Stored employee payroll jurisdiction history has no open-ended current range."
        )


def list_employee_payroll_jurisdictions(db, employee_id: int):
    history = _ordered_employee_history(db, employee_id)
    _validate_employee_history(history)
    return history


def serialize_employee_payroll_jurisdiction(record):
    return {
        "country_code": record.country_code,
        "province_code": record.province_code,
        "regulatory_scope": record.regulatory_scope,
        "effective_from": record.effective_from.isoformat(),
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
    }


def add_employee_payroll_jurisdiction(
    db,
    *,
    employee_id: int,
    country_code: str,
    province_code: str,
    regulatory_scope: str,
    effective_from: date,
):
    """Append a prospective employee province assignment without rewriting payroll."""
    if country_code != SUPPORTED_COUNTRY:
        raise PayrollJurisdictionError("country_code must be CA for this setting.")
    if province_code is None or province_code not in SUPPORTED_PROVINCES:
        raise PayrollJurisdictionError(
            "province_code must be one of: AB, BC, MB, NB, NL, NS, ON, PE, SK."
        )
    if regulatory_scope != SUPPORTED_SCOPE:
        raise PayrollJurisdictionError(
            "Only provincially regulated workplaces are supported; federal payroll is not supported."
        )
    if effective_from < MIN_EFFECTIVE_DATE:
        raise PayrollJurisdictionError("effective_from must be 2026-01-01 or later.")

    lock_company_payroll_jurisdiction(db)
    company_mode = resolve_company_payroll_jurisdiction(
        db, effective_from, lock=True
    )
    if company_mode is None:
        raise PayrollJurisdictionError(
            "Canadian country mode must be effective on the employee province assignment date."
        )

    if db.query(Employee.id).filter(Employee.id == employee_id).first() is None:
        raise PayrollJurisdictionError(f"Employee {employee_id} does not exist.")

    processed_run = (
        db.query(PayRun.id)
        .join(PayStub, PayStub.pay_run_id == PayRun.id)
        .filter(
            PayStub.employee_id == employee_id,
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.period_end >= effective_from,
        )
        .first()
    )
    if processed_run is not None:
        raise EmployeePayrollJurisdictionConflict(
            "A processed pay period for this employee intersects or follows the proposed effective date."
        )

    history = _ordered_employee_history(db, employee_id, lock=True)
    _validate_employee_history(history)
    today = date.today()
    if not history:
        if effective_from < today:
            raise PayrollJurisdictionError(
                "The initial employee province must be effective today or prospectively."
            )
    else:
        latest = history[-1]
        if effective_from <= today:
            raise PayrollJurisdictionError(
                "An employee province change must be prospective (effective from a future date)."
            )
        if effective_from <= latest.effective_from:
            raise EmployeePayrollJurisdictionConflict(
                "A new effective range must be later than the latest scheduled employee change."
            )
        if province_code == latest.province_code:
            raise EmployeePayrollJurisdictionConflict(
                "The selected province is already scheduled for this employee."
            )
        latest.effective_to = effective_from - timedelta(days=1)

    record = EmployeePayrollJurisdiction(
        employee_id=employee_id,
        country_code=country_code,
        province_code=province_code,
        regulatory_scope=regulatory_scope,
        effective_from=effective_from,
        effective_to=None,
    )
    db.add(record)
    response = {
        "employee_id": employee_id,
        **serialize_employee_payroll_jurisdiction(record),
    }
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_expected_timeline_unique_conflict(exc, employee=True):
            raise EmployeePayrollJurisdictionConflict(
                "A payroll jurisdiction range already exists for that employee effective date."
            ) from exc
        raise
    return response


def resolve_employee_payroll_jurisdiction(
    db, employee_id: int, period_start: date, period_end: date
):
    """Resolve one employee province only if it covers the entire pay period."""
    if period_start > period_end:
        raise PayrollJurisdictionError("period_start must be on or before period_end.")
    history = _ordered_employee_history(db, employee_id)
    _validate_employee_history(history)
    cursor = period_start
    provinces = set()
    first = None
    for item in history:
        if item.effective_to is not None and item.effective_to < cursor:
            continue
        if item.effective_from > period_end:
            break
        if item.effective_from > cursor:
            raise EmployeePayrollJurisdictionAmbiguous(
                "Employee payroll jurisdiction has no continuous coverage for this period."
            )
        if item.effective_to is not None and item.effective_to < cursor:
            continue
        if first is None:
            first = item
        provinces.add(item.province_code)
        if item.effective_to is None or item.effective_to >= period_end:
            break
        cursor = item.effective_to + timedelta(days=1)
    else:
        item = None

    covered = first is not None and (
        item is None
        or item.effective_to is None
        or item.effective_to >= period_end
    )
    if not covered:
        raise EmployeePayrollJurisdictionAmbiguous(
            "Employee payroll jurisdiction has no continuous coverage for this period."
        )
    if len(provinces) > 1:
        raise EmployeePayrollJurisdictionAmbiguous(
            "More than one province intersects the employee's pay period."
        )
    return first
