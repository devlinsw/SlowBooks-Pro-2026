"""Validation, append-only history maintenance, and as-of resolution.

Pay-run creation can later call ``resolve_company_payroll_jurisdiction`` with
its pay date, then snapshot the returned country/province on the run. This
service never edits payroll runs or employee work-state fields.
"""

import sqlite3
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.payroll import PayRun, PayRunStatus
from app.models.payroll_jurisdiction import PayrollJurisdiction

SUPPORTED_COUNTRY = "CA"
SUPPORTED_PROVINCES = frozenset({"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK"})
SUPPORTED_SCOPE = "provincially_regulated"
MIN_EFFECTIVE_DATE = date(2026, 1, 1)


_GUARD_TRANSACTION_INFO_KEY = "payroll_jurisdiction_guard_transaction"


def lock_company_payroll_jurisdiction(db):
    """Serialize jurisdiction activation with guarded legacy-US writes.

    This must be the first database operation in a guarded mutation. SQLite has
    no row locks, so a zero-row UPDATE takes its database writer lock even when
    jurisdiction history is empty. PostgreSQL takes a transaction-scoped table
    lock, which also protects the empty-history case. Both remain held until the
    caller commits or rolls back. Unsupported dialects and lock failures fail
    closed.
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
        elif dialect == "postgresql":
            db.execute(
                text(
                    "LOCK TABLE company_payroll_jurisdictions "
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
            )
        else:
            raise RuntimeError(
                f"Payroll jurisdiction guard locking is unsupported for {dialect}."
            )
    except Exception:
        db.rollback()
        raise

    db.info[_GUARD_TRANSACTION_INFO_KEY] = db.get_transaction()


class PayrollJurisdictionError(ValueError):
    """A jurisdiction setting does not satisfy input validation."""


class PayrollJurisdictionConflict(PayrollJurisdictionError):
    """A setting conflicts with an existing effective-dated timeline."""


class PayrollJurisdictionAmbiguous(PayrollJurisdictionConflict):
    """Stored effective ranges overlap or leave an unresolved gap."""


def _ordered_history(db, *, lock=False):
    query = db.query(PayrollJurisdiction).order_by(
        PayrollJurisdiction.effective_from.asc(), PayrollJurisdiction.id.asc()
    )
    if lock:
        query = query.with_for_update()
    history = query.all()
    if lock and history:
        # At READ COMMITTED, a SELECT FOR UPDATE that waited on a row lock may
        # return the updated row from its old statement snapshot without rows
        # inserted by the transaction it waited for. A fresh statement both
        # sees those rows and refreshes already-loaded ORM instances.
        history = query.populate_existing().all()
    return history


def _validate_history(history):
    """Require one contiguous timeline, with only the final range open."""
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


def resolve_company_payroll_jurisdiction(db, as_of: date):
    """Resolve the company's provincial jurisdiction for a date, or return None.

    Callers creating a pay run should resolve by its pay date and persist a
    snapshot on that run; never re-resolve posted run history later.
    """
    history = _ordered_history(db)
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
    return matches[0] if matches else None


def list_company_payroll_jurisdictions(db):
    history = _ordered_history(db)
    _validate_history(history)
    return history


def serialize_company_payroll_jurisdiction(record):
    """Snapshot a jurisdiction's API values while its ORM state is loaded."""
    return {
        "country_code": record.country_code,
        "province_code": record.province_code,
        "regulatory_scope": record.regulatory_scope,
        "effective_from": record.effective_from.isoformat(),
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
    }


def _is_expected_timeline_unique_conflict(exc):
    """Identify only the uniqueness constraints that protect the timeline."""
    expected_constraints = {
        "uq_company_payroll_jurisdiction_effective_from",
        "uq_company_payroll_jurisdiction_open_range",
    }
    original = exc.orig
    constraint_name = getattr(getattr(original, "diag", None), "constraint_name", None)
    if constraint_name in expected_constraints:
        return True
    if isinstance(original, sqlite3.IntegrityError):
        return str(original) in {
            "UNIQUE constraint failed: company_payroll_jurisdictions.effective_from",
            "UNIQUE constraint failed: index 'uq_company_payroll_jurisdiction_open_range'",
        }
    return False


def add_company_payroll_jurisdiction(
    db,
    *,
    country_code: str,
    province_code: str,
    effective_from: date,
    regulatory_scope: str,
):
    """Append a province change; keep prior records and only close their range."""
    if country_code != SUPPORTED_COUNTRY:
        raise PayrollJurisdictionError("country_code must be CA for this setting.")
    if province_code not in SUPPORTED_PROVINCES:
        raise PayrollJurisdictionError(
            "province_code must be one of: AB, BC, MB, NB, NL, NS, ON, PE, SK."
        )
    if regulatory_scope != SUPPORTED_SCOPE:
        raise PayrollJurisdictionError(
            "Only provincially regulated workplaces are supported; federal payroll is not supported."
        )
    if effective_from < MIN_EFFECTIVE_DATE:
        raise PayrollJurisdictionError(
            "effective_from must be 2026-01-01 or later."
        )
    lock_company_payroll_jurisdiction(db)
    processed_run = (
        db.query(PayRun.id)
        .filter(
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= effective_from,
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
    if not history:
        if effective_from < today:
            raise PayrollJurisdictionError(
                "The initial payroll jurisdiction must be effective today or prospectively."
            )
    else:
        latest = history[-1]
        if effective_from == latest.effective_from:
            raise PayrollJurisdictionConflict(
                "A payroll jurisdiction range already exists for that effective date."
            )
        if effective_from <= today:
            raise PayrollJurisdictionError(
                "A payroll province change must be prospective (effective from a future date)."
            )
        if effective_from <= latest.effective_from:
            raise PayrollJurisdictionConflict(
                "A new effective range must be later than the latest scheduled change."
            )
        if province_code == latest.province_code:
            raise PayrollJurisdictionConflict(
                "The selected province is already scheduled for this company."
            )
        latest.effective_to = effective_from - timedelta(days=1)

    record = PayrollJurisdiction(
        country_code=country_code,
        province_code=province_code,
        regulatory_scope=regulatory_scope,
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
                "A payroll jurisdiction range already exists for that effective date."
            ) from exc
        raise
    return response
