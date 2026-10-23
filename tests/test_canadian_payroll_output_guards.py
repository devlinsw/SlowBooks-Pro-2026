"""Read-side guards for legacy U.S. output over Canadian payroll periods."""

from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub


def _employee(client):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "Casey",
            "last_name": "Output",
            "pay_type": "hourly",
            "pay_rate": 25,
            "work_state": "WA",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _jurisdiction(client, effective_from):
    return client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": "CA", "effective_from": effective_from.isoformat()},
    )


def _create_draft(client, employee_id, period_start, period_end, pay_date):
    response = client.post(
        "/api/payroll",
        json={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "pay_date": pay_date.isoformat(),
            "stubs": [{"employee_id": employee_id, "gross_override": 1000}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_legacy_processed_run(
    db_session,
    employee_id,
    *,
    period_start,
    period_end,
    pay_date,
    gross=1000,
    federal=100,
):
    run = PayRun(
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
        status=PayRunStatus.PROCESSED,
        run_type=PayRunType.REGULAR,
        total_gross=gross,
        total_taxes=federal,
        total_net=gross - federal,
    )
    db_session.add(run)
    db_session.flush()
    stub = PayStub(
        pay_run_id=run.id,
        employee_id=employee_id,
        gross_pay=gross,
        federal_tax=federal,
        state_tax=20,
        ss_tax=62,
        medicare_tax=14.5,
        net_pay=gross - federal - 20 - 62 - 14.5,
        work_state="WA",
        futa_tax=6,
    )
    db_session.add(stub)
    db_session.commit()
    return run, stub


def _legacy_draft_overlapping_canada(client, employee_id):
    today = date.today()
    safe = _create_draft(
        client,
        employee_id,
        today - timedelta(days=5),
        today - timedelta(days=2),
        today - timedelta(days=1),
    )
    unsafe = _create_draft(
        client,
        employee_id,
        today,
        today + timedelta(days=5),
        today + timedelta(days=5),
    )
    configured = _jurisdiction(client, today + timedelta(days=2))
    assert configured.status_code == 201, configured.text
    return safe, unsafe


def test_pay_run_listing_filters_unsafe_rows_before_pagination(client):
    employee = _employee(client)
    safe, unsafe = _legacy_draft_overlapping_canada(client, employee["id"])

    response = client.get("/api/payroll?skip=0&limit=1")

    assert response.status_code == 200, response.text
    assert [run["id"] for run in response.json()] == [safe["id"]]
    assert unsafe["id"] not in [run["id"] for run in response.json()]
    assert response.json()[0]["stubs"][0]["federal_tax"] > 0


def test_pay_run_detail_blocks_legacy_us_fields_for_overlapping_period(client):
    employee = _employee(client)
    _safe, unsafe = _legacy_draft_overlapping_canada(client, employee["id"])

    response = client.get(f"/api/payroll/{unsafe['id']}")

    assert response.status_code == 422, response.text
    assert "Canadian" in response.json()["detail"]
    assert "stubs" not in response.json()


def test_paystub_blocks_before_ytd_or_pdf_for_overlapping_period(
    client, monkeypatch
):
    from app.routes.payroll import exports
    from app.services import paystub_pdf

    employee = _employee(client)
    _safe, unsafe = _legacy_draft_overlapping_canada(client, employee["id"])
    pdf_spy = Mock(return_value=b"unsafe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)
    stub_id = unsafe["stubs"][0]["id"]

    response = client.get(f"/api/payroll/{unsafe['id']}/paystub/{stub_id}")

    assert response.status_code == 422, response.text
    pdf_spy.assert_not_called()
    ytd_spy.assert_not_called()


@pytest.mark.parametrize("status", [PayRunStatus.DRAFT, PayRunStatus.VOID])
def test_paystub_rejects_nonprocessed_target_before_ytd_or_pdf(
    client, db_session, monkeypatch, status
):
    from app.routes.payroll import exports
    from app.services import paystub_pdf

    employee = _employee(client)
    today = date.today()
    run = _create_draft(client, employee["id"], today, today, today)
    stored_run = db_session.get(PayRun, run["id"])
    stored_run.status = status
    db_session.commit()
    pdf_spy = Mock(return_value=b"unsafe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)

    response = client.get(
        f"/api/payroll/{run['id']}/paystub/{run['stubs'][0]['id']}"
    )

    assert response.status_code == 400, response.text
    assert "processed" in response.json()["detail"].lower()
    pdf_spy.assert_not_called()
    ytd_spy.assert_not_called()
    assert db_session.get(PayRun, run["id"]).status is status


def test_paystub_blocks_when_ytd_includes_legacy_canadian_run_before_ytd_or_pdf(
    client, db_session, monkeypatch
):
    from app.routes.payroll import exports
    from app.services import paystub_pdf

    employee = _employee(client)
    effective_from = date.today() + timedelta(days=1)
    safe_run, safe_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from - timedelta(days=14),
        period_end=effective_from - timedelta(days=8),
        pay_date=effective_from - timedelta(days=1),
        gross=1000,
        federal=100,
    )
    configured = _jurisdiction(client, effective_from)
    assert configured.status_code == 201, configured.text
    _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from,
        period_end=effective_from + timedelta(days=6),
        pay_date=effective_from - timedelta(days=2),
        gross=2000,
        federal=200,
    )
    pdf_spy = Mock(return_value=b"unsafe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)

    response = client.get(
        f"/api/payroll/{safe_run.id}/paystub/{safe_stub.id}"
    )

    assert response.status_code == 422, response.text
    pdf_spy.assert_not_called()
    ytd_spy.assert_not_called()


def test_paystub_rejects_orphan_history_before_ytd_or_pdf(
    client, db_session, monkeypatch
):
    from app.routes.payroll import exports
    from app.services import paystub_pdf

    employee = _employee(client)
    pay_date = date.today()
    target_run, target_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=pay_date - timedelta(days=14),
        period_end=pay_date - timedelta(days=1),
        pay_date=pay_date,
        gross=1000,
        federal=100,
    )
    orphan_stub = PayStub(
        pay_run_id=999999,
        employee_id=employee["id"],
        gross_pay=90000,
        net_pay=70000,
    )
    db_session.add(orphan_stub)
    db_session.commit()

    before_runs = db_session.query(
        PayRun.id, PayRun.status, PayRun.total_gross, PayRun.total_net
    ).order_by(PayRun.id).all()
    before_stubs = db_session.query(
        PayStub.id,
        PayStub.pay_run_id,
        PayStub.employee_id,
        PayStub.gross_pay,
        PayStub.net_pay,
    ).filter(PayStub.employee_id == employee["id"]).order_by(PayStub.id).all()
    pdf_spy = Mock(return_value=b"unsafe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)

    response = client.get(
        f"/api/payroll/{target_run.id}/paystub/{target_stub.id}"
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "Payroll YTD history is ambiguous; a stub has no parent pay run."
    )
    ytd_spy.assert_not_called()
    pdf_spy.assert_not_called()
    assert db_session.query(
        PayRun.id, PayRun.status, PayRun.total_gross, PayRun.total_net
    ).order_by(PayRun.id).all() == before_runs
    assert db_session.query(
        PayStub.id,
        PayStub.pay_run_id,
        PayStub.employee_id,
        PayStub.gross_pay,
        PayStub.net_pay,
    ).filter(PayStub.employee_id == employee["id"]).order_by(PayStub.id).all() == before_stubs


def test_paystub_ytd_excludes_later_canadian_period_and_keeps_safe_pdf(
    client, db_session, monkeypatch
):
    from app.routes.payroll import exports
    from app.services import paystub_pdf

    employee = _employee(client)
    effective_from = date.today() + timedelta(days=1)
    _earlier_run, earlier_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from - timedelta(days=28),
        period_end=effective_from - timedelta(days=22),
        pay_date=effective_from - timedelta(days=21),
        gross=500,
        federal=50,
    )
    safe_run, safe_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from - timedelta(days=14),
        period_end=effective_from - timedelta(days=8),
        pay_date=effective_from - timedelta(days=2),
        gross=1000,
        federal=100,
    )
    configured = _jurisdiction(client, effective_from)
    assert configured.status_code == 201, configured.text
    _future_run, future_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from,
        period_end=effective_from + timedelta(days=6),
        pay_date=effective_from + timedelta(days=7),
        gross=2000,
        federal=200,
    )
    pdf_spy = Mock(return_value=b"safe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)

    response = client.get(
        f"/api/payroll/{safe_run.id}/paystub/{safe_stub.id}"
    )

    assert response.status_code == 200, response.text
    assert response.content == b"safe PDF"
    ytd_spy.assert_called_once()
    rendered_ytd = pdf_spy.call_args.args[4]
    rendered_stubs = pdf_spy.call_args.kwargs["ytd_stubs"]
    assert rendered_ytd["federal"] == "150.00"
    assert {stub.id for stub in rendered_stubs} == {earlier_stub.id, safe_stub.id}
    assert future_stub.id not in {stub.id for stub in rendered_stubs}


def test_paystub_ytd_excludes_historical_void_run(client, db_session, monkeypatch):
    from app.routes.payroll import exports, ytd as payroll_ytd
    from app.services import paystub_pdf

    employee = _employee(client)
    year_start = date(date.today().year, 1, 1)
    earlier_pay_date = year_start + timedelta(days=4)
    void_pay_date = year_start + timedelta(days=11)
    target_pay_date = year_start + timedelta(days=18)
    effective_from = max(
        date.today() + timedelta(days=30), target_pay_date + timedelta(days=1)
    )

    _earlier_run, earlier_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=year_start,
        period_end=earlier_pay_date - timedelta(days=1),
        pay_date=earlier_pay_date,
        gross=500,
        federal=50,
    )
    void_run, void_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=earlier_pay_date + timedelta(days=1),
        period_end=void_pay_date - timedelta(days=1),
        pay_date=void_pay_date,
        gross=9000,
        federal=900,
    )
    void_run.status = PayRunStatus.VOID
    db_session.commit()
    target_run, target_stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=void_pay_date + timedelta(days=1),
        period_end=target_pay_date - timedelta(days=1),
        pay_date=target_pay_date,
        gross=1000,
        federal=100,
    )
    configured = _jurisdiction(client, effective_from)
    assert configured.status_code == 201, configured.text

    actual_ytd_stubs = payroll_ytd._ytd_stubs
    queried_stubs = []

    def observe_ytd_stubs(*args, **kwargs):
        stubs = actual_ytd_stubs(*args, **kwargs)
        queried_stubs.append(stubs)
        return stubs

    pdf_spy = Mock(return_value=b"safe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    monkeypatch.setattr(payroll_ytd, "_ytd_stubs", observe_ytd_stubs)
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)

    response = client.get(
        f"/api/payroll/{target_run.id}/paystub/{target_stub.id}"
    )

    assert response.status_code == 200, response.text
    assert response.content == b"safe PDF"
    ytd_spy.assert_called_once()
    assert len(queried_stubs) == 1
    assert {stub.id for stub in queried_stubs[0]} == {
        earlier_stub.id,
        target_stub.id,
    }
    rendered_ytd = pdf_spy.call_args.args[4]
    rendered_stubs = pdf_spy.call_args.kwargs["ytd_stubs"]
    assert rendered_ytd["federal"] == "150.00"
    assert rendered_ytd["gross"] == "1500.00"
    assert {stub.id for stub in rendered_stubs} == {
        earlier_stub.id,
        target_stub.id,
    }
    assert void_stub.id not in {stub.id for stub in rendered_stubs}


def test_nacha_blocks_legacy_processed_canadian_run_before_generation(
    client, db_session, monkeypatch
):
    from app.services import nacha_export

    employee = _employee(client)
    effective_from = date.today() + timedelta(days=1)
    configured = _jurisdiction(client, effective_from)
    assert configured.status_code == 201, configured.text
    run, _stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from,
        period_end=effective_from + timedelta(days=6),
        pay_date=effective_from + timedelta(days=7),
    )
    nacha_spy = Mock(return_value="unsafe NACHA")
    monkeypatch.setattr(nacha_export, "generate_nacha_file", nacha_spy)

    response = client.post(
        f"/api/payroll/{run.id}/nacha",
        json={
            "immediate_destination": "123456789",
            "immediate_origin": "ABC1234567",
            "originating_dfi_id": "12345678",
        },
    )

    assert response.status_code == 422, response.text
    nacha_spy.assert_not_called()


def test_employee_ytd_blocks_current_year_but_preserves_wholly_us_prior_year(
    client, db_session, monkeypatch
):
    from app.routes import employees

    employee = _employee(client)
    _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 14),
        pay_date=date(2025, 1, 20),
        gross=500,
        federal=50,
    )
    effective_from = date.today() + timedelta(days=1)
    configured = _jurisdiction(client, effective_from)
    assert configured.status_code == 201, configured.text
    _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from,
        period_end=effective_from + timedelta(days=6),
        pay_date=effective_from + timedelta(days=7),
        gross=1000,
        federal=100,
    )

    prior_year = client.get(f"/api/employees/{employee['id']}/ytd?year=2025")
    assert prior_year.status_code == 200, prior_year.text
    assert prior_year.json()["gross"] == 500
    assert prior_year.json()["federal"] == 50

    ytd_spy = Mock(wraps=employees.employee_ytd)
    monkeypatch.setattr(employees, "employee_ytd", ytd_spy)
    current_year = client.get(
        f"/api/employees/{employee['id']}/ytd?year={date.today().year}"
    )

    assert current_year.status_code == 422, current_year.text
    ytd_spy.assert_not_called()


def test_portal_paystub_list_excludes_unsafe_but_keeps_pre_effective_us_stub(
    client, db_session
):
    employee = _employee(client)
    token_response = client.get(f"/api/employees/{employee['id']}/portal-token")
    assert token_response.status_code == 200, token_response.text
    effective_from = date.today() + timedelta(days=1)
    _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from - timedelta(days=10),
        period_end=effective_from - timedelta(days=4),
        pay_date=effective_from - timedelta(days=2),
        gross=111.11,
        federal=11,
    )
    configured = _jurisdiction(client, effective_from)
    assert configured.status_code == 201, configured.text
    _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=effective_from,
        period_end=effective_from + timedelta(days=6),
        pay_date=effective_from + timedelta(days=7),
        gross=999.99,
        federal=99,
    )
    client.cookies.set("slowbooks_portal", token_response.json()["portal_token"])

    response = client.get("/portal/paystubs")

    assert response.status_code == 200, response.text
    assert "$111.11" in response.text
    assert "$999.99" not in response.text


def test_export_lock_failures_block_pdf_ytd_and_nacha(client, monkeypatch):
    from app.routes.payroll import exports
    from app.services import nacha_export, paystub_pdf

    employee = _employee(client)
    today = date.today()
    run = _create_draft(
        client, employee["id"], today, today, today
    )
    pdf_spy = Mock(return_value=b"unsafe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    nacha_spy = Mock(return_value="unsafe NACHA")
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)
    monkeypatch.setattr(nacha_export, "generate_nacha_file", nacha_spy)

    def fail_lock(_db):
        raise RuntimeError("simulated lock failure")

    monkeypatch.setattr(
        exports, "lock_company_payroll_jurisdiction", fail_lock, raising=False
    )
    stub_id = run["stubs"][0]["id"]
    pdf_response = client.get(f"/api/payroll/{run['id']}/paystub/{stub_id}")
    nacha_response = client.post(
        f"/api/payroll/{run['id']}/nacha",
        json={
            "immediate_destination": "123456789",
            "immediate_origin": "ABC1234567",
            "originating_dfi_id": "12345678",
        },
    )

    assert pdf_response.status_code == 503, pdf_response.text
    assert nacha_response.status_code == 503, nacha_response.text
    pdf_spy.assert_not_called()
    ytd_spy.assert_not_called()
    nacha_spy.assert_not_called()


def test_employee_ytd_lock_failure_blocks_before_ytd_query(client, monkeypatch):
    from app.routes import employees

    employee = _employee(client)
    ytd_spy = Mock(wraps=employees.employee_ytd)
    monkeypatch.setattr(employees, "employee_ytd", ytd_spy)

    def fail_lock(_db):
        raise RuntimeError("simulated lock failure")

    monkeypatch.setattr(employees, "lock_company_payroll_jurisdiction", fail_lock)
    response = client.get(f"/api/employees/{employee['id']}/ytd?year=2025")

    assert response.status_code == 503, response.text
    ytd_spy.assert_not_called()


@pytest.mark.parametrize("path", ["/api/payroll", "/api/payroll/999999"])
def test_run_read_lock_failure_precedes_database_lookup(client, monkeypatch, path):
    from app.routes.payroll import runs as payroll_runs

    def fail_lock(_db):
        raise RuntimeError("simulated lock failure")

    monkeypatch.setattr(payroll_runs, "lock_company_payroll_jurisdiction", fail_lock)
    response = client.get(path)

    assert response.status_code == 503, response.text


def test_portal_first_lock_failure_precedes_authentication_audit(
    client, db_session, monkeypatch
):
    from app.models.portal_access import PortalAccess
    from app.routes import portal

    def fail_lock(_db):
        raise RuntimeError("simulated initial lock failure")

    monkeypatch.setattr(portal, "lock_company_payroll_jurisdiction", fail_lock)
    response = client.get("/portal/paystubs")

    assert response.status_code == 503, response.text
    assert db_session.query(PortalAccess).count() == 0


def test_portal_lock_failure_after_auth_commit_does_not_render_paystubs(
    client, db_session, monkeypatch
):
    from app.models.portal_access import PortalAccess
    from app.routes import portal

    employee = _employee(client)
    token_response = client.get(f"/api/employees/{employee['id']}/portal-token")
    client.cookies.set("slowbooks_portal", token_response.json()["portal_token"])
    real_lock = portal.lock_company_payroll_jurisdiction
    calls = 0

    def fail_second_lock(db):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated post-auth lock failure")
        return real_lock(db)

    monkeypatch.setattr(portal, "lock_company_payroll_jurisdiction", fail_second_lock)
    response = client.get("/portal/paystubs")

    assert response.status_code == 503, response.text
    assert calls == 2
    assert (
        db_session.query(PortalAccess)
        .filter(PortalAccess.employee_id == employee["id"])
        .count()
        == 1
    )


def test_target_period_history_read_failure_blocks_paystub_and_nacha_outputs(
    client, db_session, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError

    from app.routes.payroll import exports
    from app.services import nacha_export, paystub_pdf
    from app.services.payroll_jurisdiction_service import is_us_payroll_period

    employee = _employee(client)
    pay_date = date.today()
    period_start = pay_date - timedelta(days=14)
    period_end = pay_date - timedelta(days=1)
    run, stub = _seed_legacy_processed_run(
        db_session,
        employee["id"],
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
    )
    assert run.status is PayRunStatus.PROCESSED
    assert is_us_payroll_period(db_session, period_start, period_end)

    pdf_spy = Mock(return_value=b"unsafe PDF")
    ytd_spy = Mock(wraps=exports.employee_ytd)
    nacha_spy = Mock(return_value="unsafe NACHA")
    jurisdiction_read_spy = Mock(
        side_effect=SQLAlchemyError("sensitive history database detail")
    )
    monkeypatch.setattr(paystub_pdf, "generate_paystub_pdf", pdf_spy)
    monkeypatch.setattr(exports, "employee_ytd", ytd_spy)
    monkeypatch.setattr(nacha_export, "generate_nacha_file", nacha_spy)
    monkeypatch.setattr(exports, "is_us_payroll_period", jurisdiction_read_spy)
    from fastapi.testclient import TestClient

    from app.main import app

    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)

    paystub_response = request_client.get(
        f"/api/payroll/{run.id}/paystub/{stub.id}"
    )
    nacha_response = request_client.post(
        f"/api/payroll/{run.id}/nacha",
        json={
            "immediate_destination": "123456789",
            "immediate_origin": "ABC1234567",
            "originating_dfi_id": "12345678",
        },
    )

    expected_detail = (
        "Payroll jurisdiction history is unavailable; payroll output is blocked."
    )
    assert paystub_response.status_code == 503, paystub_response.text
    assert paystub_response.json()["detail"] == expected_detail
    assert "sensitive history database detail" not in paystub_response.text
    assert nacha_response.status_code == 503, nacha_response.text
    assert nacha_response.json()["detail"] == expected_detail
    assert "sensitive history database detail" not in nacha_response.text
    assert jurisdiction_read_spy.call_count == 2
    ytd_spy.assert_not_called()
    pdf_spy.assert_not_called()
    nacha_spy.assert_not_called()
