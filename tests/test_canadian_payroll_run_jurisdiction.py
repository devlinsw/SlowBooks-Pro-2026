"""Fail-closed Canadian pay-run jurisdiction snapshot boundary."""

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _employee(client):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "Casey",
            "last_name": "Test",
            "pay_type": "hourly",
            "pay_rate": 25,
            "work_state": "WA",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _jurisdiction(client, province, effective_from):
    # Company mode is country-only; employee province is configured separately.
    return client.post(
        "/api/settings/payroll-jurisdiction",
        json={
            "country_code": "CA",
            "effective_from": effective_from.isoformat(),
        },
    )


def _run(
    client,
    employee_id,
    pay_date,
    *,
    period_start=None,
    period_end=None,
    use_time_entries=False,
):
    return client.post(
        "/api/payroll",
        json={
            "period_start": (period_start or pay_date).isoformat(),
            "period_end": (period_end or pay_date).isoformat(),
            "pay_date": pay_date.isoformat(),
            "stubs": [
                {
                    "employee_id": employee_id,
                    "gross_override": None if use_time_entries else 1000,
                    "hours": 8 if use_time_entries else 0,
                    "use_time_entries": use_time_entries,
                }
            ],
        },
    )


def test_us_pay_run_without_canadian_history_keeps_legacy_behavior_and_null_snapshot(
    client, db_session
):
    from app.models.payroll import Employee, PayRun, PayStub

    employee = _employee(client)
    pay_date = date.today()

    response = _run(client, employee["id"], pay_date)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert "jurisdiction_snapshot" in payload
    assert payload["jurisdiction_snapshot"] is None
    assert payload["stubs"][0]["gross_pay"] == 1000
    assert db_session.query(PayRun).count() == 1
    assert db_session.query(PayStub).count() == 1
    assert db_session.query(Employee).filter_by(id=employee["id"]).one()


def test_active_canadian_jurisdiction_is_blocked_before_run_stub_or_time_mutation(
    client, db_session
):
    from app.models.payroll import PayRun, PayStub
    from app.models.time_entries import TimeEntry, TimeEntryStatus

    employee = _employee(client)
    pay_date = date.today()
    configured = _jurisdiction(client, "AB", pay_date)
    assert configured.status_code == 201, configured.text
    entry = TimeEntry(
        employee_id=employee["id"],
        date=pay_date,
        hours_regular=8,
        hours_overtime=0,
        hours_doubletime=0,
        status=TimeEntryStatus.APPROVED,
    )
    db_session.add(entry)
    db_session.commit()
    entry_id = entry.id

    response = _run(client, employee["id"], pay_date, use_time_entries=True)

    assert response.status_code == 422, response.text
    assert (
        "Canadian payroll calculation support is not enabled yet"
        in response.json()["detail"]
    )
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0
    persisted_entry = db_session.query(TimeEntry).filter_by(id=entry_id).one()
    assert persisted_entry.pay_run_id is None
    assert persisted_entry.status is TimeEntryStatus.APPROVED
    assert persisted_entry.hours_regular == 8


def test_future_only_jurisdiction_keeps_pre_start_us_pay_run_legacy_behavior(
    client, db_session
):
    from app.models.payroll import PayRun, PayStub

    employee = _employee(client)
    today = date.today()
    configured = _jurisdiction(client, "AB", today + timedelta(days=5))
    assert configured.status_code == 201, configured.text

    response = _run(client, employee["id"], today)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["jurisdiction_snapshot"] is None
    assert payload["stubs"][0]["gross_pay"] == 1000
    assert db_session.query(PayRun).count() == 1
    assert db_session.query(PayRun).one().jurisdiction_snapshot is None
    assert db_session.query(PayStub).count() == 1


def test_create_period_crossing_canadian_activation_fails_before_us_calculation(
    client, db_session, monkeypatch
):
    from app.models.payroll import PayRun, PayStub
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    effective_from = date(2026, 10, 25)
    configured = _jurisdiction(client, "AB", effective_from)
    assert configured.status_code == 201, configured.text

    calculator_calls = []
    real_calculator = payroll_runs.calculate_withholdings

    def calculator_spy(*args, **kwargs):
        calculator_calls.append((args, kwargs))
        return real_calculator(*args, **kwargs)

    monkeypatch.setattr(payroll_runs, "calculate_withholdings", calculator_spy)
    period_start = effective_from - timedelta(days=1)
    period_end = effective_from + timedelta(days=3)
    response = _run(
        client,
        employee["id"],
        period_start,
        period_start=period_start,
        period_end=period_end,
    )
    observed = {
        "status_code": response.status_code,
        "response": response.json(),
        "calculator_calls": len(calculator_calls),
        "run_count": db_session.query(PayRun).count(),
        "stub_count": db_session.query(PayStub).count(),
    }

    assert observed["status_code"] == 422, observed
    assert "cross" in observed["response"]["detail"].lower(), observed
    assert calculator_calls == []
    assert observed["run_count"] == 0
    assert observed["stub_count"] == 0


def test_wholly_pre_canadian_period_keeps_legacy_us_creation(
    client, db_session
):
    from app.models.payroll import PayRun, PayStub

    employee = _employee(client)
    effective_from = date(2026, 10, 25)
    configured = _jurisdiction(client, "AB", effective_from)
    assert configured.status_code == 201, configured.text
    period_start = effective_from - timedelta(days=5)
    period_end = effective_from - timedelta(days=2)
    pay_date = effective_from - timedelta(days=1)

    response = _run(
        client,
        employee["id"],
        pay_date,
        period_start=period_start,
        period_end=period_end,
    )

    assert response.status_code == 201, response.text
    assert response.json()["jurisdiction_snapshot"] is None
    assert response.json()["stubs"][0]["federal_tax"] > 0
    assert db_session.query(PayRun).count() == 1
    assert db_session.query(PayStub).count() == 1


@pytest.mark.parametrize("start_offset", [0, 1])
def test_period_starting_on_or_after_canadian_activation_is_blocked(
    client, db_session, start_offset
):
    from app.models.payroll import PayRun, PayStub

    employee = _employee(client)
    effective_from = date(2026, 10, 25)
    configured = _jurisdiction(client, "AB", effective_from)
    assert configured.status_code == 201, configured.text
    period_start = effective_from + timedelta(days=start_offset)
    period_end = period_start + timedelta(days=3)

    response = _run(
        client,
        employee["id"],
        period_start,
        period_start=period_start,
        period_end=period_end,
    )

    assert response.status_code == 422, response.text
    assert "Canadian payroll calculation support is not enabled yet" in response.json()[
        "detail"
    ]
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0


def test_ambiguous_jurisdiction_history_fails_closed_without_a_run(
    client, db_session
):
    from app.models.payroll import PayRun, PayStub
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    employee = _employee(client)
    today = date.today()
    db_session.add_all(
        [
            PayrollJurisdiction(
                country_code="CA",
                province_code="AB",
                regulatory_scope="provincially_regulated",
                effective_from=today,
                effective_to=today + timedelta(days=2),
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today + timedelta(days=2),
                effective_to=None,
            ),
        ]
    )
    db_session.commit()

    response = _run(client, employee["id"], today + timedelta(days=2))

    assert response.status_code == 409, response.text
    assert "ambiguous" in response.json()["detail"].lower()
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0


def test_snapshot_is_copied_and_api_reads_stored_value_after_timeline_changes(
    client, db_session
):
    from app.models.payroll import PayRun
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.routes.payroll.runs import _payroll_jurisdiction_snapshot
    from app.services.payroll_jurisdiction_service import (
        resolve_company_payroll_jurisdiction,
    )

    today = date.today()
    change_date = today + timedelta(days=30)
    earlier = PayrollJurisdiction(
        country_code="CA",
        province_code="AB",
        regulatory_scope="provincially_regulated",
        effective_from=today,
        effective_to=None,
    )
    db_session.add(earlier)
    db_session.flush()
    pay_date = today + timedelta(days=10)
    snapshot = _payroll_jurisdiction_snapshot(
        resolve_company_payroll_jurisdiction(db_session, pay_date), pay_date
    )
    # Seed a stored-snapshot fixture directly: the create endpoint blocks
    # Canadian runs until a reviewed Canadian calculation engine exists.
    run = PayRun(
        period_start=pay_date,
        period_end=pay_date,
        pay_date=pay_date,
        jurisdiction_snapshot=snapshot,
    )
    db_session.add(run)
    db_session.commit()
    run_id = run.id

    earlier.effective_to = change_date - timedelta(days=1)
    db_session.add(
        PayrollJurisdiction(
            country_code="CA",
            province_code="ON",
            regulatory_scope="provincially_regulated",
            effective_from=change_date,
            effective_to=None,
        )
    )
    db_session.commit()
    later = resolve_company_payroll_jurisdiction(db_session, change_date)
    assert later is not None

    detail = client.get(f"/api/payroll/{run_id}")
    listing = client.get("/api/payroll")
    later_snapshot = _payroll_jurisdiction_snapshot(later, change_date)

    expected_snapshot = {
        "jurisdiction_id": earlier.id,
        "country_code": "CA",
        "province_code": None,
        "regulatory_scope": "provincially_regulated",
        "effective_from": today.isoformat(),
        "effective_to": None,
        "pay_date": pay_date.isoformat(),
    }
    assert detail.status_code == 200, detail.text
    assert detail.json()["jurisdiction_snapshot"] == expected_snapshot
    assert listing.status_code == 200, listing.text
    listed_run = next(item for item in listing.json() if item["id"] == run_id)
    assert listed_run["jurisdiction_snapshot"] == expected_snapshot
    assert later.province_code is None
    assert later_snapshot == {
        "jurisdiction_id": later.id,
        "country_code": "CA",
        "province_code": None,
        "regulatory_scope": "provincially_regulated",
        "effective_from": change_date.isoformat(),
        "effective_to": None,
        "pay_date": change_date.isoformat(),
    }
    stored_run = db_session.query(PayRun).filter_by(id=run_id).one()
    assert stored_run.jurisdiction_snapshot == expected_snapshot


def test_pay_run_jurisdiction_snapshot_migration_is_nullable_and_reversible(tmp_path):
    root = Path(__file__).resolve().parents[1]
    migration_path = next(
        (root / "migrations" / "versions").glob("*_payrun_jurisdiction_snapshot.py")
    )
    spec = importlib.util.spec_from_file_location(
        "payrun_jurisdiction_snapshot_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'payrun-snapshot-migration.db').as_posix()}"
    )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE pay_runs (id INTEGER PRIMARY KEY, "
            "period_start DATE NOT NULL, period_end DATE NOT NULL, pay_date DATE NOT NULL)"
        )
        connection.execute(
            text(
                "INSERT INTO pay_runs (id, period_start, period_end, pay_date) "
                "VALUES (1, '2026-10-01', '2026-10-15', '2026-10-20')"
            )
        )
        operations = MigrationContext.configure(connection)
        with Operations.context(operations):
            migration.upgrade()
        column = next(
            item
            for item in inspect(connection).get_columns("pay_runs")
            if item["name"] == "jurisdiction_snapshot"
        )
        assert column["nullable"] is True
        assert connection.execute(
            text("SELECT jurisdiction_snapshot FROM pay_runs WHERE id = 1")
        ).scalar() is None

        with Operations.context(operations):
            migration.downgrade()
        assert "jurisdiction_snapshot" not in {
            item["name"] for item in inspect(connection).get_columns("pay_runs")
        }

        with Operations.context(operations):
            migration.upgrade()
        column = next(
            item
            for item in inspect(connection).get_columns("pay_runs")
            if item["name"] == "jurisdiction_snapshot"
        )
        assert column["nullable"] is True
        assert connection.execute(
            text("SELECT jurisdiction_snapshot FROM pay_runs WHERE id = 1")
        ).scalar() is None

    engine.dispose()


def _process(client, run_id):
    return client.post(f"/api/payroll/{run_id}/process")


def test_existing_us_draft_cannot_be_processed_after_canadian_activation(
    client, db_session, seed_accounts
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.models.job_costing import JobCost
    from app.models.transactions import Transaction, TransactionLine

    employee = _employee(client)
    pay_date = date.today()
    created = _run(client, employee["id"], pay_date)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    assert created.json()["jurisdiction_snapshot"] is None

    configured = _jurisdiction(client, "AB", pay_date)
    assert configured.status_code == 201, configured.text

    response = _process(client, run_id)

    assert response.status_code == 422, response.text
    assert "Canadian payroll calculation support is not enabled yet" in response.json()["detail"]
    stored = db_session.get(PayRun, run_id)
    assert stored.status is PayRunStatus.DRAFT
    assert stored.jurisdiction_snapshot is None
    assert stored.transaction_id is None
    assert stored.burden_job_cost_id is None
    assert db_session.query(PayrollJurisdiction).one().effective_from == pay_date
    assert db_session.query(Transaction).count() == 0
    assert db_session.query(TransactionLine).count() == 0
    assert db_session.query(JobCost).count() == 0


def test_processing_run_with_canadian_snapshot_fails_closed(
    client, db_session, seed_accounts
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.transactions import Transaction

    employee = _employee(client)
    created = _run(client, employee["id"], date.today())
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    run = db_session.get(PayRun, run_id)
    run.jurisdiction_snapshot = {
        "country_code": "CA",
        "province_code": "ON",
        "regulatory_scope": "provincially_regulated",
        "pay_date": date.today().isoformat(),
    }
    db_session.commit()

    response = _process(client, run_id)

    assert response.status_code == 422, response.text
    assert db_session.get(PayRun, run_id).status is PayRunStatus.DRAFT
    assert db_session.get(PayRun, run_id).transaction_id is None
    assert db_session.query(Transaction).count() == 0


@pytest.mark.parametrize("invalid_timeline", ["overlap", "gap"])
def test_processing_with_ambiguous_jurisdiction_history_fails_closed(
    client, db_session, seed_accounts, invalid_timeline
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.models.transactions import Transaction

    employee = _employee(client)
    today = date.today()
    created = _run(client, employee["id"], today)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    if invalid_timeline == "overlap":
        history = [
            PayrollJurisdiction(
                country_code="CA",
                province_code="AB",
                regulatory_scope="provincially_regulated",
                effective_from=today - timedelta(days=2),
                effective_to=today + timedelta(days=2),
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today,
                effective_to=None,
            ),
        ]
    else:
        history = [
            PayrollJurisdiction(
                country_code="CA",
                province_code="AB",
                regulatory_scope="provincially_regulated",
                effective_from=today - timedelta(days=4),
                effective_to=today - timedelta(days=2),
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today,
                effective_to=None,
            ),
        ]
    db_session.add_all(history)
    db_session.commit()

    response = _process(client, run_id)

    assert response.status_code == 409, response.text
    expected_detail = "uncovered" if invalid_timeline == "gap" else "ambiguous"
    assert expected_detail in response.json()["detail"].lower()
    assert db_session.get(PayRun, run_id).status is PayRunStatus.DRAFT
    assert db_session.get(PayRun, run_id).transaction_id is None
    assert db_session.query(Transaction).count() == 0


def test_processing_period_crossing_canadian_activation_fails_before_posting(
    client, db_session, seed_accounts
):
    from app.models.job_costing import JobCost
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.transactions import Transaction, TransactionLine

    employee = _employee(client)
    effective_from = date(2026, 10, 25)
    period_start = effective_from - timedelta(days=1)
    period_end = effective_from + timedelta(days=3)
    created = _run(
        client,
        employee["id"],
        period_start,
        period_start=period_start,
        period_end=period_end,
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    configured = _jurisdiction(client, "AB", effective_from)
    assert configured.status_code == 201, configured.text
    response = _process(client, run_id)

    stored = db_session.get(PayRun, run_id)
    observed = {
        "status_code": response.status_code,
        "response": response.json(),
        "status": stored.status.value,
        "transaction_id": stored.transaction_id,
        "burden_job_cost_id": stored.burden_job_cost_id,
        "transaction_count": db_session.query(Transaction).count(),
        "transaction_line_count": db_session.query(TransactionLine).count(),
        "job_cost_count": db_session.query(JobCost).count(),
    }
    assert observed["status_code"] == 422, observed
    assert "cross" in observed["response"]["detail"].lower(), observed
    assert stored.status is PayRunStatus.DRAFT
    assert stored.transaction_id is None
    assert stored.burden_job_cost_id is None
    assert observed["transaction_count"] == 0
    assert observed["transaction_line_count"] == 0
    assert observed["job_cost_count"] == 0


def test_processing_without_jurisdiction_history_keeps_legacy_us_behavior(
    client, db_session, seed_accounts
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.transactions import Transaction

    employee = _employee(client)
    created = _run(client, employee["id"], date.today())
    assert created.status_code == 201, created.text

    response = _process(client, created.json()["id"])

    assert response.status_code == 200, response.text
    stored = db_session.get(PayRun, created.json()["id"])
    assert stored.status is PayRunStatus.PROCESSED
    assert stored.jurisdiction_snapshot is None
    assert stored.transaction_id is not None
    assert db_session.query(Transaction).count() == 1


def test_processing_before_future_canadian_start_keeps_legacy_us_behavior(
    client, db_session, seed_accounts
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.transactions import Transaction

    employee = _employee(client)
    pay_date = date.today()
    created = _run(client, employee["id"], pay_date)
    assert created.status_code == 201, created.text
    configured = _jurisdiction(client, "AB", pay_date + timedelta(days=5))
    assert configured.status_code == 201, configured.text

    response = _process(client, created.json()["id"])

    assert response.status_code == 200, response.text
    stored = db_session.get(PayRun, created.json()["id"])
    assert stored.status is PayRunStatus.PROCESSED
    assert stored.jurisdiction_snapshot is None
    assert stored.transaction_id is not None
    assert db_session.query(Transaction).count() == 1


def test_pre_effective_historical_us_run_remains_processable(
    client, db_session, seed_accounts
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.transactions import Transaction

    employee = _employee(client)
    pay_date = date.today() - timedelta(days=1)
    created = _run(client, employee["id"], pay_date)
    assert created.status_code == 201, created.text
    configured = _jurisdiction(client, "AB", date.today())
    assert configured.status_code == 201, configured.text

    response = _process(client, created.json()["id"])

    assert response.status_code == 200, response.text
    stored = db_session.get(PayRun, created.json()["id"])
    assert stored.status is PayRunStatus.PROCESSED
    assert stored.jurisdiction_snapshot is None
    assert stored.transaction_id is not None
    assert db_session.query(Transaction).count() == 1


def test_processing_lock_failure_returns_503_without_posting(
    client, db_session, seed_accounts, monkeypatch
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.job_costing import JobCost
    from app.models.transactions import Transaction, TransactionLine
    from app.routes.payroll import runs

    employee = _employee(client)
    created = _run(client, employee["id"], date.today())
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    def fail_lock(_db):
        raise RuntimeError("simulated jurisdiction lock failure")

    monkeypatch.setattr(runs, "lock_company_payroll_jurisdiction", fail_lock)

    response = _process(client, run_id)

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == (
        "Payroll jurisdiction status is unavailable; pay-run processing is blocked."
    )
    stored = db_session.get(PayRun, run_id)
    assert stored.status is PayRunStatus.DRAFT
    assert stored.transaction_id is None
    assert stored.burden_job_cost_id is None
    assert db_session.query(Transaction).count() == 0
    assert db_session.query(TransactionLine).count() == 0
    assert db_session.query(JobCost).count() == 0
