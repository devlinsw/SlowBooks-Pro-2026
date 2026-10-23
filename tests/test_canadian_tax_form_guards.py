"""Canadian-period fail-closed coverage for U.S. payroll forms and rechecks."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.models.document_audit import DocumentAudit
from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub


CANADIAN_SNAPSHOT = {
    "country_code": "CA",
    "province_code": "AB",
    "regulatory_scope": "provincially_regulated",
    "pay_date": "2027-01-15",
}


def _employee(client):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "Taylor",
            "last_name": "Taxform",
            "pay_type": "hourly",
            "pay_rate": 25,
            "work_state": "WA",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _activate_canada(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": "CA", "effective_from": "2027-01-01"},
    )
    assert response.status_code == 201, response.text


def _seed_run(
    db_session,
    employee_id,
    *,
    period_start=date(2027, 1, 1),
    period_end=date(2027, 1, 14),
    pay_date=date(2027, 1, 15),
    company_snapshot=None,
    employee_snapshot=None,
):
    run = PayRun(
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
        status=PayRunStatus.PROCESSED,
        run_type=PayRunType.REGULAR,
        jurisdiction_snapshot=company_snapshot,
        total_gross=1000,
        total_taxes=200,
        total_net=800,
    )
    db_session.add(run)
    db_session.flush()
    stub = PayStub(
        pay_run_id=run.id,
        employee_id=employee_id,
        gross_pay=1000,
        federal_tax=100,
        state_tax=20,
        ss_tax=62,
        employer_ss_tax=62,
        medicare_tax=14.5,
        employer_medicare_tax=14.5,
        futa_tax=6,
        suta_tax=5,
        net_pay=803.5,
        work_state="WA",
        employee_jurisdiction_snapshot=employee_snapshot,
    )
    db_session.add(stub)
    db_session.commit()
    return run, stub


def _seed_audit(db_session, doc_type="w2", doc_key="emp1-yr2027"):
    audit = DocumentAudit(
        doc_type=doc_type,
        doc_key=doc_key,
        content_hash="a" * 64,
        username="test",
    )
    db_session.add(audit)
    db_session.commit()
    return audit


def _form_stubs():
    """Supply valid values if an unguarded implementation reaches a form."""
    return {
        "year": 2027,
        "quarter": 1,
        "employee_id": 1,
        "num_stubs": 1,
        "num_w2": 1,
        "num_employees": 1,
        "box1_federal_wages": 1000,
        "box2_federal_tax_withheld": 100,
        "box3_ss_wages": 1000,
        "box4_ss_tax_withheld": 62,
        "box5_medicare_wages": 1000,
        "box6_medicare_tax_withheld": 14.5,
        "box16_state_wages": 1000,
        "box17_state_income_tax": 20,
        "total_wages": 1000,
        "federal_income_tax_withheld": 100,
        "social_security_wages": 1000,
        "social_security_tax": 124,
        "medicare_wages": 1000,
        "medicare_tax": 29,
        "total_tax_liability": 253,
        "futa_taxable_wages": 1000,
        "total_futa_tax": 6,
        "total_payments": 1000,
        "exempt_payments": 0,
    }


def test_all_payroll_tax_form_routes_and_recheck_block_active_canada(
    client, db_session, monkeypatch
):
    from app.routes import tax_forms
    from app.routes.payroll import tax_forms as payroll_tax_forms

    employee = _employee(client)
    _activate_canada(client)
    _seed_run(db_session, employee["id"])
    audit = _seed_audit(db_session)

    # A call means the route got as far as U.S. calculation or PDF generation.
    calls = []
    def fake_for(name):
        def fake(*args, **kwargs):
            calls.append((name, args, kwargs))
            return b"fake PDF" if name.startswith("generate_") else _form_stubs()

        return fake

    for module, names in (
        (tax_forms, ("compute_941", "compute_940", "compute_w2", "compute_w3", "compute_all_w2", "compute_sui", "compute_tax_liability", "generate_941_pdf", "generate_940_pdf", "generate_w2_pdf")),
        (payroll_tax_forms, ("compute_941", "compute_940", "compute_w2", "compute_w3", "generate_941_pdf", "generate_940_pdf", "generate_w2_pdf", "generate_w3_pdf")),
    ):
        for name in names:
            target = getattr(module, name) if hasattr(module, name) else getattr(module, {"compute_941": "form_941", "compute_940": "form_940", "compute_w2": "w2_w3", "compute_w3": "w2_w3", "compute_all_w2": "w2_w3", "compute_sui": "state_sui", "compute_tax_liability": "tax_liability", "generate_941_pdf": "form_941", "generate_940_pdf": "form_940", "generate_w2_pdf": "w2_w3"}[name])
            fake = fake_for(name)
            if hasattr(target, name):
                monkeypatch.setattr(target, name, fake)
            else:
                monkeypatch.setattr(module, name, fake)
    company_payload = {"name": "Test Co", "ein": "12-3456789", "address": "1 Main St"}
    monkeypatch.setattr(payroll_tax_forms, "employer_block", Mock(return_value=company_payload))
    monkeypatch.setattr(tax_forms, "_company", Mock(return_value=company_payload))

    paths = [
        ("GET", "/api/tax-forms/941?year=2027&quarter=1"),
        ("GET", "/api/tax-forms/941/pdf?year=2027&quarter=1"),
        ("GET", "/api/tax-forms/940?year=2027"),
        ("GET", "/api/tax-forms/940/pdf?year=2027"),
        ("GET", "/api/tax-forms/w2?year=2027"),
        ("GET", f"/api/tax-forms/w2/{employee['id']}?year=2027"),
        ("GET", f"/api/tax-forms/w2/{employee['id']}/pdf?year=2027"),
        ("GET", "/api/tax-forms/sui?year=2027&quarter=1"),
        ("GET", "/api/tax-forms/liability?year=2027&quarter=1"),
        ("POST", f"/api/payroll/forms/w2/{employee['id']}?year=2027"),
        ("POST", "/api/payroll/forms/w3/2027"),
        ("POST", "/api/payroll/forms/940/2027"),
        ("POST", "/api/payroll/forms/941/2027/1"),
        ("GET", f"/api/payroll/forms/w2/{employee['id']}/pdf?year=2027"),
        ("POST", f"/api/payroll/forms/w2/{employee['id']}/pdf?year=2027"),
        ("GET", "/api/payroll/forms/w3/2027/pdf"),
        ("POST", "/api/payroll/forms/w3/2027/pdf"),
        ("GET", "/api/payroll/forms/940/2027/pdf"),
        ("POST", "/api/payroll/forms/940/2027/pdf"),
        ("GET", "/api/payroll/forms/941/2027/1/pdf"),
        ("POST", "/api/payroll/forms/941/2027/1/pdf"),
    ]
    before_audits = db_session.query(DocumentAudit).count()
    responses = [client.request(method, path) for method, path in paths]
    check = client.get(f"/api/document-audits/{audit.id}/check")

    assert len(paths) == 21
    assert [response.status_code for response in responses] == [422] * len(paths)
    assert check.status_code == 422, check.text
    assert calls == []
    assert db_session.query(DocumentAudit).count() == before_audits


def test_safe_pre_activation_period_and_no_history_keep_us_output(client, db_session):
    employee = _employee(client)
    _activate_canada(client)
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 14),
        pay_date=date(2025, 12, 15),
    )

    response = client.get("/api/tax-forms/w2?year=2025")
    no_history_response = client.get("/api/tax-forms/940?year=2024")

    assert response.status_code == 200, response.text
    assert response.json()["w2"][0]["gross_pay"] == 1000
    assert no_history_response.status_code == 200, no_history_response.text


def test_nonempty_pre_activation_history_remains_available_through_json_and_pdfs(
    client, db_session, monkeypatch
):
    from io import BytesIO

    from pypdf import PdfReader

    from app.routes import payroll_jurisdiction
    from app.services import payroll_jurisdiction_service

    server_today = date(2025, 10, 23)

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return server_today

    monkeypatch.setattr(payroll_jurisdiction, "date", FrozenDate)
    monkeypatch.setattr(payroll_jurisdiction_service, "date", FrozenDate)

    employee = _employee(client)
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 14),
        pay_date=date(2025, 12, 15),
    )
    activation = client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": "CA", "effective_from": "2026-01-01"},
    )
    assert activation.status_code == 201, activation.text
    assert activation.json()["effective_from"] == "2026-01-01"
    # Restore date type checks for database-loaded ordinary date values.
    monkeypatch.setattr(payroll_jurisdiction_service, "date", date)

    json_paths = [
        f"/api/payroll/forms/w2/{employee['id']}?year=2025",
        "/api/payroll/forms/w3/2025",
        "/api/payroll/forms/940/2025",
        "/api/payroll/forms/941/2025/4",
    ]
    for path in json_paths:
        response = client.post(path)
        assert response.status_code == 200, f"{path}: {response.text}"
        assert response.json()["box_1"] == "1000.00", path

    pdf_paths = [
        ("GET", f"/api/payroll/forms/w2/{employee['id']}/pdf?year=2025", "FORM W-2"),
        ("POST", f"/api/payroll/forms/w2/{employee['id']}/pdf?year=2025", "FORM W-2"),
        ("GET", "/api/payroll/forms/w3/2025/pdf", "FORM W-3"),
        ("POST", "/api/payroll/forms/w3/2025/pdf", "FORM W-3"),
        ("GET", "/api/payroll/forms/940/2025/pdf", "FORM 940"),
        ("POST", "/api/payroll/forms/940/2025/pdf", "FORM 940"),
        ("GET", "/api/payroll/forms/941/2025/4/pdf", "FORM 941"),
        ("POST", "/api/payroll/forms/941/2025/4/pdf", "FORM 941"),
    ]
    for method, path, title in pdf_paths:
        response = client.request(method, path)
        assert response.status_code == 200, f"{method} {path}: {response.text}"
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF-")
        assert len(response.content) > 1024
        text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(BytesIO(response.content)).pages
        )
        assert title in text, path
        assert "$1,000.00" in text, path
        if "/w2/" in path:
            assert "Taylor Taxform" in text

    legacy_pdf = client.get("/api/tax-forms/940/pdf?year=2025")
    assert legacy_pdf.status_code == 200, legacy_pdf.text
    assert legacy_pdf.headers["content-type"] == "application/pdf"
    assert legacy_pdf.content.startswith(b"%PDF-")
    legacy_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(BytesIO(legacy_pdf.content)).pages
    )
    assert "FORM 940" in legacy_text
    assert "$1,000.00" in legacy_text


def test_legacy_tax_forms_keep_populated_safe_history_after_canada_activation(
    client, db_session, monkeypatch
):
    from app.routes import payroll_jurisdiction, tax_forms
    from app.services import payroll_jurisdiction_service

    server_today = date(2025, 10, 23)

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return server_today

    monkeypatch.setattr(payroll_jurisdiction, "date", FrozenDate)
    monkeypatch.setattr(payroll_jurisdiction_service, "date", FrozenDate)

    employee = _employee(client)
    _run, stub = _seed_run(
        db_session,
        employee["id"],
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 14),
        pay_date=date(2025, 12, 15),
    )
    activation = client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": "CA", "effective_from": "2026-01-01"},
    )
    assert activation.status_code == 201, activation.text
    assert activation.json()["effective_from"] == "2026-01-01"
    monkeypatch.setattr(payroll_jurisdiction_service, "date", date)

    json_responses = {
        "941": client.get("/api/tax-forms/941?year=2025&quarter=4"),
        "940": client.get("/api/tax-forms/940?year=2025"),
        "all_w2": client.get("/api/tax-forms/w2?year=2025"),
        "employee_w2": client.get(
            f"/api/tax-forms/w2/{employee['id']}?year=2025"
        ),
        "sui": client.get(
            "/api/tax-forms/sui?year=2025&quarter=4&state=WA"
        ),
        "liability": client.get(
            "/api/tax-forms/liability?year=2025&quarter=4"
        ),
    }
    for name, response in json_responses.items():
        assert response.status_code == 200, f"{name}: {response.text}"

    form_941 = json_responses["941"].json()
    assert form_941["num_stubs"] == 1
    assert form_941["total_wages"] == 1000
    assert form_941["federal_income_tax_withheld"] == 100

    form_940 = json_responses["940"].json()
    assert form_940["num_stubs"] == 1
    assert form_940["total_payments"] == 1000
    assert form_940["total_futa_tax"] == 6

    all_w2 = json_responses["all_w2"].json()
    assert all_w2["w3"]["num_w2"] == 1
    assert all_w2["w2"][0]["gross_pay"] == 1000
    assert all_w2["w2"][0]["employee"]["name"] == "Taylor Taxform"

    employee_w2 = json_responses["employee_w2"].json()
    assert employee_w2["num_stubs"] == 1
    assert employee_w2["gross_pay"] == 1000
    assert employee_w2["box2_federal_tax_withheld"] == 100

    sui = json_responses["sui"].json()
    assert sui["num_employees"] == 1
    assert sui["total_wages"] == 1000
    assert sui["employees"][0]["suta_tax"] == 5

    liability = json_responses["liability"].json()
    assert liability["num_stubs"] == 1
    assert liability["total_due"] == 284.0
    assert [item["amount"] for item in liability["liabilities"]] == [
        253.0,
        6.0,
        5.0,
        20.0,
        0.0,
    ]

    renderers = {
        "941": (tax_forms.form_941, "generate_941_pdf", "total_wages"),
        "940": (tax_forms.form_940, "generate_940_pdf", "total_payments"),
        "w2": (tax_forms.w2_w3, "generate_w2_pdf", "gross_pay"),
    }
    renderer_spies = {}
    for key, (module, name, data_key) in renderers.items():
        spy = Mock(wraps=getattr(module, name))
        monkeypatch.setattr(module, name, spy)
        renderer_spies[key] = (spy, data_key)

    pdf_responses = {
        "941": client.get("/api/tax-forms/941/pdf?year=2025&quarter=4"),
        "940": client.get("/api/tax-forms/940/pdf?year=2025"),
        "w2": client.get(
            f"/api/tax-forms/w2/{employee['id']}/pdf?year=2025"
        ),
    }
    for name, response in pdf_responses.items():
        assert response.status_code == 200, f"{name}: {response.text}"
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF-")
        assert len(response.content) > 1024

        spy, data_key = renderer_spies[name]
        spy.assert_called_once()
        call = spy.call_args
        assert [contributor.id for contributor in call.kwargs["stubs"]] == [
            stub.id
        ]
        assert call.kwargs["data"][data_key] == Decimal("1000.00")


def test_contributor_full_period_crossing_activation_blocks_pre_activation_tax_year(
    client, db_session, monkeypatch
):
    from app.routes import tax_forms

    employee = _employee(client)
    _activate_canada(client)
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 12, 20),
        period_end=date(2027, 1, 1),
        pay_date=date(2026, 12, 31),
    )
    calculator = Mock(wraps=tax_forms.w2_w3.compute_w2)
    monkeypatch.setattr(tax_forms.w2_w3, "compute_w2", calculator)

    response = client.get("/api/tax-forms/w2?year=2026")

    assert response.status_code == 422, response.text
    calculator.assert_not_called()


def test_941_validates_its_full_ytd_contributor_window(client, db_session):
    employee = _employee(client)
    _activate_canada(client)
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 12, 20),
        period_end=date(2027, 1, 1),
        pay_date=date(2026, 12, 31),
    )

    response = client.get("/api/tax-forms/941?year=2026&quarter=4")

    assert response.status_code == 422, response.text


def test_safe_941_receives_earlier_ytd_stubs_for_wage_base_and_medicare(
    client, db_session, monkeypatch
):
    from app.routes import tax_forms

    employee = _employee(client)
    _activate_canada(client)
    q1_run, q1_stub = _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        pay_date=date(2026, 1, 15),
    )
    q1_run.total_gross = Decimal("200000")
    q1_stub.gross_pay = Decimal("200000")
    db_session.commit()
    _q2_run, q2_stub = _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 14),
        pay_date=date(2026, 4, 15),
    )

    real_compute = tax_forms.form_941.compute_941
    seen = {}

    def compute(db, year, quarter, stubs=None):
        seen["stubs"] = stubs
        return real_compute(db, year, quarter, stubs=stubs)

    monkeypatch.setattr(tax_forms.form_941, "compute_941", compute)
    response = client.get("/api/tax-forms/941?year=2026&quarter=2")

    assert response.status_code == 200, response.text
    assert seen["stubs"] is not None
    included_ids = {stub.id for stub in seen["stubs"]}
    assert {q1_stub.id, q2_stub.id} <= included_ids
    assert response.json()["num_stubs"] == 1
    assert response.json()["social_security_wages"] == 0
    assert response.json()["additional_medicare_wages"] == 1000


@pytest.mark.parametrize(
    ("company_snapshot", "employee_snapshot"),
    [(CANADIAN_SNAPSHOT, None), (None, CANADIAN_SNAPSHOT)],
)
def test_canadian_contributor_snapshots_never_feed_historical_us_w2(
    client, db_session, company_snapshot, employee_snapshot
):
    employee = _employee(client)
    _activate_canada(client)
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 14),
        pay_date=date(2025, 12, 15),
        company_snapshot=company_snapshot,
        employee_snapshot=employee_snapshot,
    )

    response = client.get(f"/api/tax-forms/w2/{employee['id']}?year=2025")

    assert response.status_code == 422, response.text


def test_orphan_processed_stub_is_ambiguous_not_silently_omitted(client, db_session):
    employee = _employee(client)
    db_session.add(
        PayStub(
            pay_run_id=999999,
            employee_id=employee["id"],
            gross_pay=90000,
            net_pay=70000,
        )
    )
    db_session.commit()

    response = client.get("/api/tax-forms/w2?year=2025")

    assert response.status_code == 409, response.text


def test_missing_employee_in_processed_stub_blocks_w2_before_calculation(
    client, db_session, monkeypatch
):
    from app.routes import tax_forms

    _seed_run(
        db_session,
        999999,
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 14),
        pay_date=date(2025, 12, 15),
    )
    calculations = []

    def compute_w3(*args, **kwargs):
        calculations.append("w3")
        return _form_stubs()

    def compute_all_w2(*args, **kwargs):
        calculations.append("all_w2")
        return [_form_stubs()]

    monkeypatch.setattr(tax_forms.w2_w3, "compute_w3", compute_w3)
    monkeypatch.setattr(tax_forms.w2_w3, "compute_all_w2", compute_all_w2)

    response = client.get("/api/tax-forms/w2?year=2025")

    assert response.status_code == 409, response.text
    assert calculations == []


def test_missing_employee_in_state_filtered_sui_blocks_before_calculation(
    client, db_session, monkeypatch
):
    from app.routes import tax_forms

    _seed_run(
        db_session,
        999999,
        period_start=date(2025, 10, 1),
        period_end=date(2025, 10, 14),
        pay_date=date(2025, 10, 15),
    )
    calculations = []

    def compute_sui(*args, **kwargs):
        calculations.append((args, kwargs))
        return {}

    monkeypatch.setattr(tax_forms.state_sui, "compute_sui", compute_sui)

    response = client.get("/api/tax-forms/sui?year=2025&quarter=4&state=WA")

    assert response.status_code == 409, response.text
    assert calculations == []


def test_ambiguous_country_history_blocks_output_with_conflict(client, db_session):
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    db_session.add_all(
        [
            PayrollJurisdiction(
                country_code="CA",
                province_code=None,
                regulatory_scope="provincially_regulated",
                effective_from=date(2027, 1, 1),
                effective_to=date(2027, 12, 31),
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code=None,
                regulatory_scope="provincially_regulated",
                effective_from=date(2027, 6, 1),
                effective_to=None,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/tax-forms/940?year=2027")

    assert response.status_code == 409, response.text


def test_jurisdiction_history_database_failure_is_generic_503(client, db_session, monkeypatch):
    from app.services import payroll_jurisdiction_service

    employee = _employee(client)
    _activate_canada(client)
    _seed_run(db_session, employee["id"])

    def fail_history(*args, **kwargs):
        raise SQLAlchemyError("private database host and query details")

    monkeypatch.setattr(payroll_jurisdiction_service, "_ordered_history", fail_history)

    response = client.get("/api/tax-forms/w2?year=2027")

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Payroll jurisdiction history is temporarily unavailable."
    assert "private database" not in response.text


def test_paystub_contributor_query_database_error_is_generic_503(
    db_session, monkeypatch
):
    from fastapi import HTTPException
    from sqlalchemy.orm import Query

    from app.services.tax_form_jurisdiction_guard import load_us_tax_form_contributors

    real_all = Query.all

    def fail_only_paystub_query(query):
        entity = query.column_descriptions[0].get("entity")
        if entity is PayStub:
            raise SQLAlchemyError("private contributor query details")
        return real_all(query)

    monkeypatch.setattr(Query, "all", fail_only_paystub_query)

    with pytest.raises(HTTPException) as exc_info:
        load_us_tax_form_contributors(
            db_session, date(2025, 1, 1), date(2025, 12, 31)
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Payroll jurisdiction history is temporarily unavailable."
    )
    assert "private contributor query" not in str(exc_info.value)


def test_unsupported_lock_backend_maps_to_generic_503():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.services.tax_form_jurisdiction_guard import lock_tax_form_jurisdiction

    class UnsupportedDialectSession:
        info = {}
        rolled_back = False

        def get_transaction(self):
            return None

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

        def execute(self, statement):
            pytest.fail("unsupported dialect must not execute a lock statement")

        def rollback(self):
            self.rolled_back = True

    db = UnsupportedDialectSession()

    with pytest.raises(HTTPException) as exc_info:
        lock_tax_form_jurisdiction(db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Payroll jurisdiction history is temporarily unavailable."
    )
    assert db.rolled_back is True


def test_unexpected_lock_runtime_error_propagates(monkeypatch):
    from app.services import tax_form_jurisdiction_guard

    def fail_unexpectedly(_db):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(
        tax_form_jurisdiction_guard,
        "lock_company_payroll_jurisdiction",
        fail_unexpectedly,
    )

    with pytest.raises(RuntimeError, match="unexpected programming failure"):
        tax_form_jurisdiction_guard.lock_tax_form_jurisdiction(object())


def test_tax_form_ui_explains_us_period_boundary_without_hiding_history_or_1099():
    from pathlib import Path

    source = Path("app/static/js/tax_forms.js").read_text()
    notice = source.lower()

    assert "u.s. payroll forms" in notice
    assert "wholly u.s." in notice
    assert "canadian periods" in notice and "blocked" in notice
    assert "canadian forms are not implemented" in notice
    assert "generatew2()" in notice and "generatew3()" in notice
    assert "taxforms-h-1099-nec-1096-contractors" in notice
    assert "generate1099()" in notice and "generate1096()" in notice


def test_safe_pdf_reuses_validated_contributors_for_calculation_hash_and_render(
    client, db_session, monkeypatch
):
    from app.routes.payroll import tax_forms as payroll_tax_forms

    employee = _employee(client)
    _activate_canada(client)
    _run, stub = _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        pay_date=date(2026, 1, 15),
    )

    real_loader = getattr(payroll_tax_forms, "annual_us_contributors", None)
    real_compute = payroll_tax_forms.compute_w3
    real_hash = payroll_tax_forms.form_content_hash
    seen = {}

    def load_contributors(db, year, **kwargs):
        contributors = (
            real_loader(db, year, **kwargs) if callable(real_loader) else [stub]
        )
        seen["contributors"] = contributors
        return contributors

    def compute(db, year, stubs=None):
        seen["calculation_contributors"] = stubs
        data = real_compute(db, year, stubs=stubs) if stubs is not None else real_compute(db, year)
        seen["data"] = data
        return data

    def hash_data(company, data):
        seen["company"] = company
        seen["hashed_data"] = data
        return real_hash(company, data)

    def render(db, year, company, audit=None, *, data=None, stubs=None):
        seen["rendered_data"] = data
        seen["render_contributors"] = stubs
        return b"validated pdf"

    monkeypatch.setattr(
        payroll_tax_forms, "annual_us_contributors", load_contributors, raising=False
    )
    monkeypatch.setattr(payroll_tax_forms, "compute_w3", compute)
    monkeypatch.setattr(payroll_tax_forms, "form_content_hash", hash_data)
    monkeypatch.setattr(payroll_tax_forms, "generate_w3_pdf", render)

    response = client.get("/api/payroll/forms/w3/2026/pdf")

    assert response.status_code == 200, response.text
    assert "contributors" in seen
    assert "calculation_contributors" in seen
    assert seen["calculation_contributors"] is seen["contributors"]
    assert seen["hashed_data"] is seen["data"]
    assert seen["rendered_data"] is seen["data"]
    assert seen["render_contributors"] is seen["contributors"]
    audit = db_session.query(DocumentAudit).filter_by(doc_type="w3").one()
    assert audit.content_hash == real_hash(seen["company"], seen["data"])


def test_pdf_render_failure_rolls_back_uncommitted_audit_row(
    client, db_session, monkeypatch
):
    from app.routes.payroll import tax_forms as payroll_tax_forms

    employee = _employee(client)
    _activate_canada(client)
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        pay_date=date(2026, 1, 15),
    )

    before_audits = db_session.query(DocumentAudit).count()

    def render_failure(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(payroll_tax_forms, "generate_w3_pdf", render_failure)
    with pytest.raises(RuntimeError, match="render failed"):
        client.get("/api/payroll/forms/w3/2026/pdf")

    assert db_session.query(DocumentAudit).count() == before_audits
