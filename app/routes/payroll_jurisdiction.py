"""Company Canadian country mode and employee province-history APIs."""

import sqlite3
from datetime import date
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.payroll import Employee
from app.services.payroll_jurisdiction_service import (
    EmployeePayrollJurisdictionConflict,
    PayrollJurisdictionAmbiguous,
    PayrollJurisdictionConflict,
    PayrollJurisdictionError,
    add_company_payroll_jurisdiction,
    add_employee_payroll_jurisdiction,
    list_company_payroll_jurisdictions,
    list_employee_payroll_jurisdictions,
    lock_company_payroll_jurisdiction,
    serialize_company_payroll_jurisdiction as _serialize_company,
    serialize_employee_payroll_jurisdiction as _serialize_employee,
)

router = APIRouter(
    prefix="/api/settings/payroll-jurisdiction", tags=["payroll jurisdiction"]
)


class PayrollJurisdictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_code: str
    effective_from: date


class EmployeePayrollJurisdictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_code: str
    province_code: str
    regulatory_scope: str
    effective_from: date

    @field_validator("regulatory_scope")
    @classmethod
    def provincially_regulated_only(cls, value):
        if value != "provincially_regulated":
            raise ValueError(
                "Only provincially regulated workplaces are supported; federal payroll is not supported."
            )
        return value


def _is_sqlite_busy_or_locked(exc: OperationalError) -> bool:
    original = exc.orig
    if not isinstance(original, sqlite3.OperationalError):
        return False
    error_code = getattr(original, "sqlite_errorcode", None)
    if error_code is not None:
        return error_code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    return str(original).lower() in {
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
    raise HTTPException(
        status_code=503,
        detail="Payroll jurisdiction status is unavailable; the request is blocked.",
    ) from exc


def _lock_before_route_io(db: Session):
    try:
        lock_company_payroll_jurisdiction(db)
    except OperationalError as exc:
        db.rollback()
        _raise_database_lock_conflict(exc)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Payroll jurisdiction status is unavailable; the request is blocked.",
        ) from exc


def _company_state(db: Session, as_of: date):
    try:
        history = list_company_payroll_jurisdictions(db)
    except PayrollJurisdictionAmbiguous as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    active = next(
        (
            item
            for item in history
            if item.effective_from <= as_of
            and (item.effective_to is None or as_of <= item.effective_to)
        ),
        None,
    )
    today = date.today()
    return {
        "country_code": active.country_code if active else None,
        "effective_from": active.effective_from.isoformat() if active else None,
        "effective_to": active.effective_to.isoformat()
        if active and active.effective_to
        else None,
        "server_today": today.isoformat(),
        "minimum_effective_from": today.isoformat() if not history else None,
        "history": [_serialize_company(item) for item in history],
    }


@router.get("")
def get_payroll_jurisdiction(
    as_of: date | None = Query(default=None), db: Session = Depends(get_db)
):
    """Return company country mode history, never a current company province."""
    _lock_before_route_io(db)
    return _company_state(db, as_of or date.today())


@router.post("", status_code=201)
def create_payroll_jurisdiction(
    data: PayrollJurisdictionCreate, db: Session = Depends(get_db)
):
    """Enable Canadian country mode prospectively without choosing a province."""
    try:
        response = add_company_payroll_jurisdiction(
            db,
            country_code=data.country_code,
            effective_from=data.effective_from,
        )
    except OperationalError as exc:
        db.rollback()
        _raise_database_lock_conflict(exc)
    except PayrollJurisdictionError as exc:
        db.rollback()
        if isinstance(exc, PayrollJurisdictionConflict):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response


@router.get("/employees/{employee_id}")
def get_employee_payroll_jurisdiction(
    employee_id: int, db: Session = Depends(get_db)
):
    """Return one employee's effective-dated province-of-employment history."""
    _lock_before_route_io(db)
    if db.query(Employee.id).filter(Employee.id == employee_id).first() is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        history = list_employee_payroll_jurisdictions(db, employee_id)
    except PayrollJurisdictionAmbiguous as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "employee_id": employee_id,
        "history": [_serialize_employee(item) for item in history],
    }


@router.post("/employees/{employee_id}", status_code=201)
def create_employee_payroll_jurisdiction(
    employee_id: int,
    data: EmployeePayrollJurisdictionCreate,
    db: Session = Depends(get_db),
):
    """Add an employee province assignment with a prospective effective date."""
    _lock_before_route_io(db)
    if db.query(Employee.id).filter(Employee.id == employee_id).first() is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        return add_employee_payroll_jurisdiction(
            db,
            employee_id=employee_id,
            country_code=data.country_code,
            province_code=data.province_code,
            regulatory_scope=data.regulatory_scope,
            effective_from=data.effective_from,
        )
    except OperationalError as exc:
        db.rollback()
        _raise_database_lock_conflict(exc)
    except PayrollJurisdictionError as exc:
        db.rollback()
        if isinstance(
            exc, (PayrollJurisdictionConflict, EmployeePayrollJurisdictionConflict)
        ):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
