"""Fail closed when U.S. calculations or YTD totals use unsafe run history."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub


def _employee(client):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "Casey",
            "last_name": "YTD Guard",
            "pay_type": "hourly",
            "pay_rate": 25,
            "work_state": "WA",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _jurisdiction(client, effective_from):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": "CA", "effective_from": effective_from.isoformat()},
    )
    assert response.status_code == 201, response.text
    return response


def _seed_run(
    db_session,
    employee_id,
    *,
    period_start,
    period_end,
    pay_date,
    gross=1000,
    federal=100,
    run_type=PayRunType.REGULAR,
    snapshot=None,
):
    run = PayRun(
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
        status=PayRunStatus.PROCESSED,
        run_type=run_type,
        jurisdiction_snapshot=snapshot,
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


def test_employee_ytd_rejects_2026_paydate_with_period_crossing_into_canada(
    client, db_session, monkeypatch
):
    from app.routes import employees

    employee = _employee(client)
    _jurisdiction(client, date(2027, 1, 1))
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 12, 20),
        period_end=date(2027, 1, 1),
        pay_date=date(2026, 12, 31),
        gross=1000,
        federal=100,
    )
    ytd_spy = Mock(wraps=employees.employee_ytd)
    monkeypatch.setattr(employees, "employee_ytd", ytd_spy)

    response = client.get(f"/api/employees/{employee['id']}/ytd?year=2026")

    assert response.status_code == 422, response.text
    ytd_spy.assert_not_called()


def test_pay_run_creation_rejects_unsafe_ytd_before_tax_or_persistence(
    client, db_session, monkeypatch
):
    from app.models.payroll import PayRun as StoredPayRun
    from app.models.payroll import PayStub as StoredPayStub
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    _jurisdiction(client, date(2027, 7, 1))
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 12, 20),
        period_end=date(2027, 7, 1),
        pay_date=date(2027, 1, 1),
        gross=1200,
    )
    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2027-01-04",
            "period_end": "2027-01-08",
            "pay_date": "2027-01-10",
            "stubs": [{"employee_id": employee["id"], "gross_override": 900}],
        },
    )

    assert response.status_code == 422, response.text
    ytd_spy.assert_not_called()
    withholding_spy.assert_not_called()
    assert db_session.query(StoredPayRun).count() == 1
    assert db_session.query(StoredPayStub).count() == 1


def test_explicit_gross_up_rejects_unsafe_ytd_before_ytd_or_tax_calculation(
    client, db_session, monkeypatch
):
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    _jurisdiction(client, date(2027, 7, 1))
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 12, 20),
        period_end=date(2027, 7, 1),
        pay_date=date(2027, 1, 1),
        gross=1200,
    )
    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    supplemental_spy = Mock(wraps=payroll_runs._ytd_supplemental)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "_ytd_supplemental", supplemental_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    response = client.post(
        "/api/payroll/gross-up",
        json={
            "employee_id": employee["id"],
            "target_net": 700,
            "supplemental": True,
            "pay_date": "2027-01-10",
        },
    )

    assert response.status_code == 422, response.text
    ytd_spy.assert_not_called()
    supplemental_spy.assert_not_called()
    withholding_spy.assert_not_called()


def test_unsafe_last_regular_gross_blocks_aggregate_supplemental_calculation(
    client, db_session, monkeypatch
):
    from app.models.payroll import PayRun as StoredPayRun
    from app.models.payroll import PayStub as StoredPayStub
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    _jurisdiction(client, date(2027, 7, 1))
    # Outside 2027 YTD by pay date, but still selected by _last_regular_gross.
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2026, 12, 20),
        period_end=date(2027, 7, 1),
        pay_date=date(2026, 12, 31),
        gross=1200,
    )
    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    supplemental_ytd_spy = Mock(wraps=payroll_runs._ytd_supplemental)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "_ytd_supplemental", supplemental_ytd_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2027-01-04",
            "period_end": "2027-01-08",
            "pay_date": "2027-01-10",
            "stubs": [
                {
                    "employee_id": employee["id"],
                    "gross_override": 900,
                    "supplemental": True,
                    "supplemental_method": "aggregate",
                }
            ],
        },
    )

    assert response.status_code == 422, response.text
    ytd_spy.assert_not_called()
    supplemental_ytd_spy.assert_not_called()
    withholding_spy.assert_not_called()
    assert db_session.query(StoredPayRun).count() == 1
    assert db_session.query(StoredPayStub).count() == 1


def test_safe_pre_canadian_ytd_is_used_and_later_canadian_run_is_excluded(
    client, db_session, monkeypatch
):
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    _jurisdiction(client, date(2027, 7, 1))
    _safe_run, safe_stub = _seed_run(
        db_session,
        employee["id"],
        period_start=date(2027, 5, 1),
        period_end=date(2027, 5, 14),
        pay_date=date(2027, 5, 20),
        gross=500,
        federal=25,
        run_type=PayRunType.BONUS,
    )
    _seed_run(
        db_session,
        employee["id"],
        period_start=date(2027, 7, 1),
        period_end=date(2027, 7, 14),
        pay_date=date(2027, 7, 20),
        gross=900,
        federal=90,
        run_type=PayRunType.BONUS,
        snapshot={
            "country_code": "CA",
            "province_code": "AB",
            "regulatory_scope": "provincially_regulated",
            "pay_date": "2027-07-20",
        },
    )
    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    supplemental_spy = Mock(wraps=payroll_runs._ytd_supplemental)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "_ytd_supplemental", supplemental_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    response = client.post(
        "/api/payroll/gross-up",
        json={
            "employee_id": employee["id"],
            "target_net": 300,
            "supplemental": True,
            "pay_date": "2027-06-01",
        },
    )

    assert response.status_code == 200, response.text
    ytd_spy.assert_called_once()
    supplemental_spy.assert_called_once()
    ytd_stubs = ytd_spy.call_args.kwargs["stubs"]
    supplemental_stubs = supplemental_spy.call_args.kwargs["stubs"]
    assert ytd_stubs is supplemental_stubs
    assert [stub.id for stub in ytd_stubs] == [safe_stub.id]
    assert ytd_spy.call_args.kwargs["before"] == date(2027, 6, 1)
    assert supplemental_spy.call_args.kwargs["before"] == date(2027, 6, 1)
    assert ytd_spy.call_args.kwargs["stubs"]
    assert withholding_spy.call_args.kwargs["ytd_gross"] == Decimal("500")
    assert withholding_spy.call_args.kwargs["ytd_supplemental"] == Decimal("500")


def test_default_gross_up_excludes_future_same_year_history_from_ytd_and_supplemental(
    client, db_session, monkeypatch
):
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    today = date(date.today().year, 1, 1)
    mocked_date = Mock()
    mocked_date.today.return_value = today
    monkeypatch.setattr(payroll_runs, "date", mocked_date)
    future_pay_date = today + timedelta(days=5)
    assert future_pay_date > today
    assert future_pay_date.year == today.year
    _future_run, future_stub = _seed_run(
        db_session,
        employee["id"],
        period_start=future_pay_date - timedelta(days=13),
        period_end=future_pay_date,
        pay_date=future_pay_date,
        gross=25000,
        federal=1000,
        run_type=PayRunType.BONUS,
    )
    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    supplemental_spy = Mock(wraps=payroll_runs._ytd_supplemental)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "_ytd_supplemental", supplemental_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    response = client.post(
        "/api/payroll/gross-up",
        json={"employee_id": employee["id"], "target_net": 700, "supplemental": True},
    )

    assert response.status_code == 200, response.text
    assert ytd_spy.call_args.kwargs["before"] == today
    assert supplemental_spy.call_args.kwargs["before"] == today
    ytd_stubs = ytd_spy.call_args.kwargs["stubs"]
    supplemental_stubs = supplemental_spy.call_args.kwargs["stubs"]
    assert ytd_stubs is supplemental_stubs
    assert ytd_stubs == []
    assert future_stub.id not in [stub.id for stub in ytd_stubs]
    assert withholding_spy.called
    assert all(
        call.kwargs["ytd_gross"] == Decimal("0")
        for call in withholding_spy.call_args_list
    )
    assert all(
        call.kwargs["ytd_supplemental"] == Decimal("0")
        for call in withholding_spy.call_args_list
    )


def test_employee_ytd_returns_generic_503_on_jurisdiction_history_read_error(
    client, db_session, monkeypatch
):
    from app.models.payroll import PayRun as StoredPayRun
    from app.models.payroll import PayStub as StoredPayStub
    from app.routes import employees

    employee = _employee(client)
    ytd_spy = Mock(wraps=employees.employee_ytd)
    monkeypatch.setattr(employees, "employee_ytd", ytd_spy)
    runs_before = db_session.query(StoredPayRun).count()
    stubs_before = db_session.query(StoredPayStub).count()

    def fail(*_args, **_kwargs):
        raise RuntimeError("sensitive history query details")

    monkeypatch.setattr(employees, "is_us_payroll_period", fail)

    response = client.get(f"/api/employees/{employee['id']}/ytd?year=2026")

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == (
        "Payroll jurisdiction status is unavailable; employee YTD is blocked."
    )
    assert "sensitive history query details" not in response.text
    ytd_spy.assert_not_called()
    assert db_session.query(StoredPayRun).count() == runs_before
    assert db_session.query(StoredPayStub).count() == stubs_before


def test_pay_run_returns_generic_503_on_jurisdiction_history_read_error(
    client, db_session, monkeypatch
):
    from app.models.payroll import PayRun as StoredPayRun
    from app.models.payroll import PayStub as StoredPayStub
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    def fail(*_args, **_kwargs):
        raise RuntimeError("sensitive history query details")

    monkeypatch.setattr(
        payroll_runs, "resolve_company_payroll_jurisdiction_for_period", fail
    )
    runs_before = db_session.query(StoredPayRun).count()
    stubs_before = db_session.query(StoredPayStub).count()

    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-11-02",
            "period_end": "2026-11-08",
            "pay_date": "2026-11-10",
            "stubs": [{"employee_id": employee["id"], "gross_override": 900}],
        },
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == (
        "Payroll jurisdiction status is unavailable; pay-run creation is blocked."
    )
    assert "sensitive history query details" not in response.text
    ytd_spy.assert_not_called()
    withholding_spy.assert_not_called()
    assert db_session.query(StoredPayRun).count() == runs_before
    assert db_session.query(StoredPayStub).count() == stubs_before


@pytest.mark.parametrize("failure_stage", ["history", "resolve"])
def test_gross_up_returns_generic_503_on_jurisdiction_history_read_error(
    client, db_session, monkeypatch, failure_stage
):
    from app.models.payroll import PayRun as StoredPayRun
    from app.models.payroll import PayStub as StoredPayStub
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    supplemental_spy = Mock(wraps=payroll_runs._ytd_supplemental)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "_ytd_supplemental", supplemental_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    def fail(*_args, **_kwargs):
        raise RuntimeError("sensitive history query details")

    if failure_stage == "history":
        monkeypatch.setattr(payroll_runs, "list_company_payroll_jurisdictions", fail)
    else:
        monkeypatch.setattr(
            payroll_runs, "list_company_payroll_jurisdictions", lambda _db: []
        )
        monkeypatch.setattr(
            payroll_runs, "resolve_company_payroll_jurisdiction", fail
        )
    runs_before = db_session.query(StoredPayRun).count()
    stubs_before = db_session.query(StoredPayStub).count()

    response = client.post(
        "/api/payroll/gross-up",
        json={"employee_id": employee["id"], "target_net": 700, "supplemental": True},
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == (
        "Payroll jurisdiction status is unavailable; gross-up calculation is blocked."
    )
    assert "sensitive history query details" not in response.text
    ytd_spy.assert_not_called()
    supplemental_spy.assert_not_called()
    withholding_spy.assert_not_called()
    assert db_session.query(StoredPayRun).count() == runs_before
    assert db_session.query(StoredPayStub).count() == stubs_before


def test_employee_ytd_treats_orphaned_stub_as_ambiguous(client, db_session):
    employee = _employee(client)
    db_session.add(PayStub(pay_run_id=999999, employee_id=employee["id"]))
    db_session.commit()

    response = client.get(f"/api/employees/{employee['id']}/ytd?year=2026")

    assert response.status_code == 409, response.text
    assert "ambiguous" in response.json()["detail"].lower()


@pytest.mark.parametrize("failure", ["lock", "query"])
def test_employee_ytd_fails_closed_on_contributor_lock_or_query_error(
    client, monkeypatch, failure
):
    from app.routes import employees
    from app.routes.payroll import ytd as ytd_helpers

    employee = _employee(client)
    ytd_spy = Mock(wraps=employees.employee_ytd)
    monkeypatch.setattr(employees, "employee_ytd", ytd_spy)

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated YTD history failure")

    if failure == "lock":
        monkeypatch.setattr(ytd_helpers, "lock_company_payroll_jurisdiction", fail)
    else:
        monkeypatch.setattr(ytd_helpers, "_ytd_stubs", fail)

    response = client.get(f"/api/employees/{employee['id']}/ytd?year=2026")

    assert response.status_code == 503, response.text
    ytd_spy.assert_not_called()
