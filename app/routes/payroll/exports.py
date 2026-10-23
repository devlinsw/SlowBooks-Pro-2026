from datetime import date

from decimal import Decimal

from fastapi import Depends, HTTPException
from fastapi.responses import Response, PlainTextResponse
from app.schemas.common import StrictModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.payroll._router import router
from app.routes.payroll.ytd import employee_ytd
from app.services.payroll_documents import employer_block
from app.services.request_utils import content_disposition, file_name
from app.models.payroll import (
    PayRun,
    PayStub,
    PayRunStatus,
    Employee,
)
from app.services.payroll_jurisdiction_service import (
    PayrollJurisdictionAmbiguous,
    PayrollJurisdictionPeriodBoundary,
    is_us_payroll_period,
    lock_company_payroll_jurisdiction,
)
from app import config


def _lock_output_read(db: Session) -> None:
    try:
        lock_company_payroll_jurisdiction(db)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Payroll jurisdiction status is unavailable; payroll output is blocked.",
        ) from exc


def _require_us_output_period(db: Session, run: PayRun) -> None:
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
    if not safe:
        raise HTTPException(
            status_code=422,
            detail="U.S. payroll outputs are unavailable for Canadian payroll periods.",
        )


@router.get("/{run_id}/paystub/{stub_id}")
def download_paystub(run_id: int, stub_id: int, db: Session = Depends(get_db)):
    """Generate the PDF pay stub for one employee on a pay run."""
    from app.services.paystub_pdf import generate_paystub_pdf

    _lock_output_read(db)
    run = db.query(PayRun).filter(PayRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    _require_us_output_period(db, run)

    stub = (
        db.query(PayStub)
        .filter(PayStub.id == stub_id, PayStub.pay_run_id == run_id)
        .first()
    )
    if not stub:
        raise HTTPException(status_code=404, detail="Pay stub not found")
    emp = db.query(Employee).filter(Employee.id == stub.employee_id).first()

    # Year to date means up to this pay date: the stubs of processed runs
    # this year dated on or before it, and this stub (a later run, or a
    # draft, is not part of what this stub reports).
    from app.models.payroll import PayRunStatus
    from app.routes.payroll.ytd import _ytd_stubs

    ytd_stubs = [
        s
        for s in _ytd_stubs(db, stub.employee_id, run.pay_date.year)
        if s.id != stub.id
        and s.pay_run.pay_date <= run.pay_date
        and s.pay_run.status == PayRunStatus.PROCESSED
    ] + [stub]
    ytd = employee_ytd(db, stub.employee_id, run.pay_date.year)
    for key, attr in (("gross", "gross_pay"), ("net", "net_pay")):
        ytd[key] = sum((getattr(s, attr) or 0 for s in ytd_stubs), Decimal("0"))
    pdf = generate_paystub_pdf(
        stub,
        emp,
        run,
        employer_block(db),
        {k: str(v) for k, v in ytd.items()},
        ytd_stubs=ytd_stubs,
    )
    # Named for the person and the pay date, not internal ids
    # ("paystub_1_1.pdf"; 2.18.0 gate, NEW-6).
    name = file_name("Pay-Stub", run.pay_date, emp.full_name if emp else None)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(name + ".pdf")},
    )


class NachaOriginating(StrictModel):
    immediate_destination: str  # receiving bank routing number
    immediate_origin: str  # company identifier (10 chars)
    destination_name: str = "BANK"
    origin_name: str = ""
    company_name: str = ""
    company_id: str = ""  # usually the employer EIN
    originating_dfi_id: str  # 8-digit routing prefix of the company's bank
    company_account: str = ""
    effective_date: date = None


@router.post("/{run_id}/nacha", response_class=PlainTextResponse)
def export_nacha(
    run_id: int, originating: NachaOriginating, db: Session = Depends(get_db)
):
    """Generate a NACHA ACH file for direct deposit of a processed pay run."""
    from app.services.nacha_export import generate_nacha_file

    _lock_output_read(db)
    run = db.query(PayRun).filter(PayRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    _require_us_output_period(db, run)
    if run.status != PayRunStatus.PROCESSED:
        raise HTTPException(
            status_code=400, detail="Pay run must be processed before ACH export"
        )

    orig = originating.model_dump()
    if not orig.get("effective_date"):
        orig["effective_date"] = run.pay_date
    if not orig.get("company_name"):
        orig["company_name"] = config.COMPANY_NAME
    if not orig.get("company_id"):
        orig["company_id"] = config.EMPLOYER_EIN

    try:
        nacha = generate_nacha_file(db, run_id, orig)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PlainTextResponse(
        content=nacha,
        headers={"Content-Disposition": f"attachment; filename=payroll_{run_id}.ach"},
    )
