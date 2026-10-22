"""Fail-closed Canadian pay-run jurisdiction snapshot boundary."""

import importlib.util
from datetime import date, timedelta
from pathlib import Path

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
    return client.post(
        "/api/settings/payroll-jurisdiction",
        json={
            "country_code": "CA",
            "province_code": province,
            "regulatory_scope": "provincially_regulated",
            "effective_from": effective_from.isoformat(),
        },
    )


def _run(client, employee_id, pay_date, *, use_time_entries=False):
    return client.post(
        "/api/payroll",
        json={
            "period_start": pay_date.isoformat(),
            "period_end": pay_date.isoformat(),
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


def test_configured_history_without_pay_date_match_fails_closed_without_a_run(
    client, db_session
):
    from app.models.payroll import PayRun, PayStub

    employee = _employee(client)
    today = date.today()
    configured = _jurisdiction(client, "AB", today + timedelta(days=5))
    assert configured.status_code == 201, configured.text

    response = _run(client, employee["id"], today)

    assert response.status_code == 422, response.text
    assert (
        "No configured payroll jurisdiction applies on the pay date"
        in response.json()["detail"]
    )
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
        "province_code": "AB",
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
    assert later.province_code == "ON"
    assert later_snapshot == {
        "jurisdiction_id": later.id,
        "country_code": "CA",
        "province_code": "ON",
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
