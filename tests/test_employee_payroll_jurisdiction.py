"""Employee-level Canadian province history and migration safety."""

from datetime import date, timedelta
from pathlib import Path

import pytest


def _country_mode_payload(effective_from):
    return {"country_code": "CA", "effective_from": effective_from.isoformat()}


def _employee_province_payload(province, effective_from, scope="provincially_regulated"):
    return {
        "country_code": "CA",
        "province_code": province,
        "regulatory_scope": scope,
        "effective_from": effective_from.isoformat(),
    }


def _employee(db_session, first_name="Test", last_name="Employee"):
    from app.models.payroll import Employee

    employee = Employee(first_name=first_name, last_name=last_name)
    db_session.add(employee)
    db_session.commit()
    return employee


def test_company_country_mode_does_not_require_or_report_legacy_province(client, db_session):
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    legacy = PayrollJurisdiction(
        country_code="CA",
        province_code="AB",
        regulatory_scope="provincially_regulated",
        effective_from=date.today(),
    )
    db_session.add(legacy)
    db_session.commit()

    response = client.get("/api/settings/payroll-jurisdiction")

    assert response.status_code == 200, response.text
    state = response.json()
    assert state["country_code"] == "CA"
    assert "province_code" not in state
    assert all("province_code" not in item for item in state["history"])
    assert db_session.query(PayrollJurisdiction).one().province_code == "AB"


def test_country_mode_can_be_activated_without_a_company_province(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_country_mode_payload(date.today()),
    )

    assert response.status_code == 201, response.text
    assert response.json()["country_code"] == "CA"
    assert "province_code" not in response.json()
    state = client.get("/api/settings/payroll-jurisdiction").json()
    assert state["country_code"] == "CA"
    assert "province_code" not in state


def test_employees_can_have_different_provinces_on_the_same_date(
    client, db_session
):
    today = date.today()
    country = client.post(
        "/api/settings/payroll-jurisdiction", json=_country_mode_payload(today)
    )
    assert country.status_code == 201, country.text
    alberta_employee = _employee(db_session, "Alex", "Alberta")
    ontario_employee = _employee(db_session, "Olivia", "Ontario")

    alberta = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{alberta_employee.id}",
        json=_employee_province_payload("AB", today),
    )
    ontario = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{ontario_employee.id}",
        json=_employee_province_payload("ON", today),
    )

    assert alberta.status_code == ontario.status_code == 201
    assert alberta.json()["province_code"] == "AB"
    assert ontario.json()["province_code"] == "ON"
    assert client.get(
        f"/api/settings/payroll-jurisdiction/employees/{alberta_employee.id}"
    ).json()["history"][0]["province_code"] == "AB"
    assert client.get(
        f"/api/settings/payroll-jurisdiction/employees/{ontario_employee.id}"
    ).json()["history"][0]["province_code"] == "ON"


def test_employee_province_api_rejects_unknown_employee_and_unsupported_province(
    client, db_session
):
    today = date.today()
    unknown = client.post(
        "/api/settings/payroll-jurisdiction/employees/999999",
        json=_employee_province_payload("AB", today),
    )
    employee = _employee(db_session)
    unsupported = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("QC", today),
    )

    assert unknown.status_code == 404, unknown.text
    assert unsupported.status_code == 422, unsupported.text


@pytest.mark.parametrize("scope", ["federally_regulated", "unknown"])
def test_employee_province_api_rejects_nonprovincial_scope(client, db_session, scope):
    employee = _employee(db_session)
    response = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("ON", date.today(), scope=scope),
    )

    assert response.status_code == 422, response.text
    assert client.get(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}"
    ).json()["history"] == []


def test_employee_resolver_accepts_single_province_pay_period_and_rejects_change(
    client, db_session
):
    from app.services.payroll_jurisdiction_service import (
        PayrollJurisdictionAmbiguous,
        add_employee_payroll_jurisdiction,
        resolve_employee_payroll_jurisdiction,
    )

    today = date.today()
    employee = _employee(db_session)
    change_date = today + timedelta(days=20)
    add_employee_payroll_jurisdiction(
        db_session,
        employee_id=employee.id,
        country_code="CA",
        province_code="AB",
        regulatory_scope="provincially_regulated",
        effective_from=today,
    )
    add_employee_payroll_jurisdiction(
        db_session,
        employee_id=employee.id,
        country_code="CA",
        province_code="BC",
        regulatory_scope="provincially_regulated",
        effective_from=change_date,
    )

    resolved = resolve_employee_payroll_jurisdiction(
        db_session, employee.id, today, today + timedelta(days=6)
    )
    assert resolved.province_code == "AB"
    with pytest.raises(PayrollJurisdictionAmbiguous, match="More than one province"):
        resolve_employee_payroll_jurisdiction(
            db_session, employee.id, change_date - timedelta(days=2), change_date
        )


def test_employee_resolver_rejects_period_without_continuous_coverage(
    db_session,
):
    from app.services.payroll_jurisdiction_service import (
        PayrollJurisdictionAmbiguous,
        add_employee_payroll_jurisdiction,
        resolve_employee_payroll_jurisdiction,
    )

    today = date.today()
    employee = _employee(db_session)
    add_employee_payroll_jurisdiction(
        db_session,
        employee_id=employee.id,
        country_code="CA",
        province_code="ON",
        regulatory_scope="provincially_regulated",
        effective_from=today,
    )

    with pytest.raises(PayrollJurisdictionAmbiguous, match="continuous coverage"):
        resolve_employee_payroll_jurisdiction(
            db_session, employee.id, today - timedelta(days=1), today
        )


def test_employee_province_history_dates_are_prospective_and_contiguous(
    client, db_session
):
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction

    today = date.today()
    employee = _employee(db_session)
    backdated = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("AB", today - timedelta(days=1)),
    )
    first = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("AB", today),
    )
    not_prospective = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("ON", today),
    )
    change_date = today + timedelta(days=1)
    scheduled = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("ON", change_date),
    )
    duplicate_date = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("BC", change_date),
    )

    assert backdated.status_code == 422, backdated.text
    assert first.status_code == 201, first.text
    assert not_prospective.status_code == 422, not_prospective.text
    assert scheduled.status_code == 201, scheduled.text
    assert duplicate_date.status_code == 409, duplicate_date.text
    history = client.get(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}"
    ).json()["history"]
    assert [item["province_code"] for item in history] == ["AB", "ON"]
    assert history[0]["effective_to"] == today.isoformat()
    assert history[1]["effective_from"] == change_date.isoformat()
    assert db_session.query(EmployeePayrollJurisdiction).count() == 2


def test_employee_province_change_cannot_reinterpret_processed_pay_period(
    client, db_session
):
    from app.models.payroll import PayRun, PayRunStatus, PayStub
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction

    today = date.today()
    employee = _employee(db_session)
    period_start = today + timedelta(days=4)
    effective_from = period_start + timedelta(days=2)
    run = PayRun(
        period_start=period_start,
        period_end=period_start + timedelta(days=6),
        pay_date=period_start + timedelta(days=9),
        status=PayRunStatus.PROCESSED,
    )
    db_session.add(run)
    db_session.flush()
    stub = PayStub(
        pay_run_id=run.id,
        employee_id=employee.id,
        gross_pay=812.34,
        federal_tax=81.23,
    )
    db_session.add(stub)
    db_session.commit()

    response = client.post(
        f"/api/settings/payroll-jurisdiction/employees/{employee.id}",
        json=_employee_province_payload("ON", effective_from),
    )

    assert response.status_code == 409, response.text
    assert db_session.query(EmployeePayrollJurisdiction).count() == 0
    assert db_session.get(PayRun, run.id).status is PayRunStatus.PROCESSED
    persisted_stub = db_session.query(PayStub).one()
    assert float(persisted_stub.gross_pay) == 812.34
    assert float(persisted_stub.federal_tax) == 81.23


def test_employee_history_unique_effective_date_is_scoped_to_employee(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction

    today = date.today()
    first = _employee(db_session, "Alex", "First")
    second = _employee(db_session, "Olivia", "Second")
    db_session.add_all(
        [
            EmployeePayrollJurisdiction(
                employee_id=first.id,
                country_code="CA",
                province_code="AB",
                regulatory_scope="provincially_regulated",
                effective_from=today,
                effective_to=today,
            ),
            EmployeePayrollJurisdiction(
                employee_id=second.id,
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today,
            ),
        ]
    )
    db_session.commit()
    db_session.add(
        EmployeePayrollJurisdiction(
            employee_id=first.id,
            country_code="CA",
            province_code="ON",
            regulatory_scope="provincially_regulated",
            effective_from=today,
            effective_to=today,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_employee_database_enforces_one_open_range_per_employee(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction

    today = date.today()
    employee = _employee(db_session)
    db_session.add_all(
        [
            EmployeePayrollJurisdiction(
                employee_id=employee.id,
                country_code="CA",
                province_code="AB",
                regulatory_scope="provincially_regulated",
                effective_from=today,
            ),
            EmployeePayrollJurisdiction(
                employee_id=employee.id,
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today + timedelta(days=1),
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_one_pay_run_persists_independent_employee_province_snapshots(client, db_session):
    from app.models.payroll import Employee, PayRun, PayStub

    today = date.today()
    alberta_employee = Employee(first_name="Alex", last_name="Snapshot")
    ontario_employee = Employee(first_name="Olivia", last_name="Snapshot")
    run = PayRun(period_start=today, period_end=today, pay_date=today)
    db_session.add_all([alberta_employee, ontario_employee, run])
    db_session.flush()
    snapshots = {
        alberta_employee.id: {
            "country_code": "CA",
            "province_code": "AB",
            "regulatory_scope": "provincially_regulated",
            "effective_from": today.isoformat(),
        },
        ontario_employee.id: {
            "country_code": "CA",
            "province_code": "ON",
            "regulatory_scope": "provincially_regulated",
            "effective_from": today.isoformat(),
        },
    }
    db_session.add_all(
        [
            PayStub(
                pay_run_id=run.id,
                employee_id=employee_id,
                gross_pay=123.45,
                employee_jurisdiction_snapshot=snapshot,
            )
            for employee_id, snapshot in snapshots.items()
        ]
    )
    db_session.commit()
    run_id = run.id
    db_session.expire_all()

    stored = db_session.query(PayStub).order_by(PayStub.employee_id).all()
    assert {
        stub.employee_id: stub.employee_jurisdiction_snapshot for stub in stored
    } == snapshots
    assert all(float(stub.gross_pay) == 123.45 for stub in stored)

    response = client.get(f"/api/payroll/{run_id}")
    assert response.status_code == 200, response.text
    assert {
        stub["employee_id"]: stub["employee_jurisdiction_snapshot"]
        for stub in response.json()["stubs"]
    } == snapshots


def test_us_company_resolver_remains_unconfigured_without_canadian_mode(db_session):
    from app.services.payroll_jurisdiction_service import (
        resolve_company_payroll_jurisdiction,
    )

    assert resolve_company_payroll_jurisdiction(db_session, date.today()) is None


def test_employee_jurisdiction_migration_backfills_all_employees_without_rewriting_payroll(
    tmp_path,
):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect, text

    root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "employee-jurisdiction-upgrade.db"
    assert not database_path.exists()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["database_url"] = f"sqlite:///{database_path.as_posix()}"
    old_head = "06ae9f5dc58e"
    script = ScriptDirectory.from_config(config)
    new_revisions = [
        revision
        for revision in script.walk_revisions()
        if revision.down_revision == old_head
    ]
    assert len(new_revisions) == 1

    engine = None
    try:
        command.upgrade(config, old_head)
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            employee_ids = []
            for first_name in ("Alex", "Olivia"):
                result = connection.execute(
                    text(
                        "INSERT INTO employees (first_name, last_name) "
                        "VALUES (:first_name, 'Worker')"
                    ),
                    {"first_name": first_name},
                )
                employee_ids.append(result.lastrowid)
            run_result = connection.execute(
                text(
                    "INSERT INTO pay_runs "
                    "(period_start, period_end, pay_date, jurisdiction_snapshot, status) "
                    "VALUES ('2025-01-01', '2025-01-07', '2025-01-10', NULL, 'PROCESSED')"
                )
            )
            run_id = run_result.lastrowid
            connection.execute(
                text(
                    "INSERT INTO pay_stubs "
                    "(pay_run_id, employee_id, gross_pay, federal_tax) "
                    "VALUES (:run_id, :employee_id, 123.45, 12.34)"
                ),
                {"run_id": run_id, "employee_id": employee_ids[0]},
            )
            connection.execute(
                text(
                    "INSERT INTO company_payroll_jurisdictions "
                    "(country_code, province_code, regulatory_scope, effective_from, effective_to) "
                    "VALUES ('CA', 'AB', 'provincially_regulated', '2024-01-01', '2024-12-31'), "
                    "('CA', 'ON', 'provincially_regulated', '2025-01-01', NULL)"
                )
            )
        engine.dispose()
        engine = None

        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.connect() as connection:
            inspector = inspect(connection)
            employee_columns = inspector.get_columns("employee_payroll_jurisdictions")
            assert {column["name"] for column in employee_columns} >= {
                "employee_id",
                "country_code",
                "province_code",
                "regulatory_scope",
                "effective_from",
                "effective_to",
            }
            company_province = next(
                column
                for column in inspector.get_columns("company_payroll_jurisdictions")
                if column["name"] == "province_code"
            )
            assert company_province["nullable"] is True
            backfilled = connection.execute(
                text(
                    "SELECT employee_id, province_code, regulatory_scope, "
                    "effective_from, effective_to "
                    "FROM employee_payroll_jurisdictions ORDER BY employee_id, effective_from"
                )
            ).all()
            expected = [
                (employee_id, province, "provincially_regulated", start, end)
                for employee_id in employee_ids
                for province, start, end in (
                    ("AB", "2024-01-01", "2024-12-31"),
                    ("ON", "2025-01-01", None),
                )
            ]
            assert [tuple(row) for row in backfilled] == expected
            legacy = connection.execute(
                text(
                    "SELECT province_code, effective_from, effective_to "
                    "FROM company_payroll_jurisdictions ORDER BY effective_from"
                )
            ).all()
            assert [tuple(row) for row in legacy] == [
                ("AB", "2024-01-01", "2024-12-31"),
                ("ON", "2025-01-01", None),
            ]
            run = connection.execute(
                text(
                    "SELECT jurisdiction_snapshot, status FROM pay_runs WHERE id = :id"
                ),
                {"id": run_id},
            ).one()
            stub = connection.execute(
                text(
                    "SELECT gross_pay, federal_tax FROM pay_stubs WHERE pay_run_id = :id"
                ),
                {"id": run_id},
            ).one()
            assert tuple(run) == (None, "PROCESSED")
            assert tuple(stub) == (123.45, 12.34)
            assert any(
                column["name"] == "employee_jurisdiction_snapshot"
                and column["nullable"]
                for column in inspector.get_columns("pay_stubs")
            )
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
        assert not database_path.exists()
