"""Company-level Canadian payroll jurisdiction settings."""

import sqlite3
from datetime import date, timedelta
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.payroll_jurisdiction import PayrollJurisdiction
from app.services.payroll_jurisdiction_service import (
    PayrollJurisdictionAmbiguous,
    PayrollJurisdictionConflict,
    PayrollJurisdictionError,
    add_company_payroll_jurisdiction,
    list_company_payroll_jurisdictions,
    resolve_company_payroll_jurisdiction,
)

router = APIRouter(
    prefix="/api/settings/payroll-jurisdiction", tags=["payroll jurisdiction"]
)


class PayrollJurisdictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_code: str
    province_code: str
    effective_from: date
    regulatory_scope: str

    @field_validator("regulatory_scope")
    @classmethod
    def provincially_regulated_only(cls, value):
        if value != "provincially_regulated":
            raise ValueError(
                "Only provincially regulated workplaces are supported; federal payroll is not supported."
            )
        return value


def _serialize(record: PayrollJurisdiction):
    return {
        "country_code": record.country_code,
        "province_code": record.province_code,
        "regulatory_scope": record.regulatory_scope,
        "effective_from": record.effective_from.isoformat(),
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
    }


def _state(db: Session, as_of: date):
    try:
        active = resolve_company_payroll_jurisdiction(db, as_of)
        history = list_company_payroll_jurisdictions(db)
    except PayrollJurisdictionAmbiguous as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    today = date.today()
    minimum_effective_from = (
        today
        if not history
        else max(
            today + timedelta(days=1), history[-1].effective_from + timedelta(days=1)
        )
    )
    return {
        "country_code": active.country_code if active else None,
        "province_code": active.province_code if active else None,
        "effective_from": active.effective_from.isoformat() if active else None,
        "effective_to": active.effective_to.isoformat()
        if active and active.effective_to
        else None,
        "regulatory_scope": "provincially_regulated",
        "minimum_effective_from": minimum_effective_from.isoformat(),
        "history": [_serialize(item) for item in history],
    }


def _is_sqlite_busy_or_locked(exc: OperationalError) -> bool:
    original = exc.orig
    if not isinstance(original, sqlite3.OperationalError):
        return False
    error_code = getattr(original, "sqlite_errorcode", None)
    if error_code is not None:
        return error_code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    message = str(original).lower()
    return message in {
        "database is busy",
        "database is locked",
        "database table is locked",
    }


def _raise_database_lock_conflict(exc: OperationalError) -> NoReturn:
    if _is_sqlite_busy_or_locked(exc):
        raise HTTPException(
            status_code=409,
            detail="Payroll jurisdiction database is busy; retry the request.",
            headers={"Retry-After": "1"},
        ) from exc
    raise exc


@router.get("")
def get_payroll_jurisdiction(
    as_of: date | None = Query(default=None), db: Session = Depends(get_db)
):
    """Return the company history and the jurisdiction effective on ``as_of``."""
    try:
        return _state(db, as_of or date.today())
    except OperationalError as exc:
        db.rollback()
        _raise_database_lock_conflict(exc)


@router.post("", status_code=201)
def create_payroll_jurisdiction(
    data: PayrollJurisdictionCreate, db: Session = Depends(get_db)
):
    """Set an initial jurisdiction or schedule a prospective province change."""
    try:
        record = add_company_payroll_jurisdiction(
            db,
            country_code=data.country_code,
            province_code=data.province_code,
            effective_from=data.effective_from,
            regulatory_scope=data.regulatory_scope,
        )
    except OperationalError as exc:
        db.rollback()
        _raise_database_lock_conflict(exc)
    except PayrollJurisdictionError as exc:
        db.rollback()
        if isinstance(exc, PayrollJurisdictionConflict):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(record)
