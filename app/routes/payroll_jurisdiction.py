"""Company-level Canadian payroll jurisdiction settings."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
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
    return {
        "country_code": active.country_code if active else None,
        "province_code": active.province_code if active else None,
        "effective_from": active.effective_from.isoformat() if active else None,
        "effective_to": active.effective_to.isoformat()
        if active and active.effective_to
        else None,
        "regulatory_scope": "provincially_regulated",
        "history": [_serialize(item) for item in history],
    }


@router.get("")
def get_payroll_jurisdiction(
    as_of: date | None = Query(default=None), db: Session = Depends(get_db)
):
    """Return the company history and the jurisdiction effective on ``as_of``."""
    return _state(db, as_of or date.today())


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
    except PayrollJurisdictionError as exc:
        db.rollback()
        if isinstance(exc, PayrollJurisdictionConflict):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(record)
