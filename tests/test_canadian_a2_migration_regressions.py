"""Task 1 migration and API regressions for Canadian jurisdiction history."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


_OLD_HEAD = "06ae9f5dc58e"
_MIGRATION_HEAD = "d8c2f4a61b90"
_INDEX_NAME = "uq_company_payroll_jurisdiction_open_range"


def _migration_config(database_path):
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["database_url"] = f"sqlite:///{database_path.as_posix()}"
    return config


def _has_open_range_index(connection):
    sql = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND name = :name"
        ),
        {"name": _INDEX_NAME},
    ).scalar_one_or_none()
    index = next(
        (
            row
            for row in connection.exec_driver_sql(
                "PRAGMA index_list('company_payroll_jurisdictions')"
            ).all()
            if row[1] == _INDEX_NAME
        ),
        None,
    )
    return bool(
        sql
        and "CREATE UNIQUE INDEX" in sql.upper()
        and "((1))" in sql
        and "effective_to IS NULL" in sql
        and index is not None
        and index[2] == 1
    )


def _second_open_range_is_rejected(connection):
    try:
        connection.execute(
            text(
                "INSERT INTO company_payroll_jurisdictions "
                "(country_code, province_code, regulatory_scope, effective_from, effective_to) "
                "VALUES ('CA', 'ON', 'provincially_regulated', '2025-01-01', NULL)"
            )
        )
    except IntegrityError:
        return True
    connection.execute(
        text(
            "DELETE FROM company_payroll_jurisdictions "
            "WHERE effective_from = '2025-01-01'"
        )
    )
    return False


def _seed_open_company_range(connection, *, employee=False):
    employee_id = None
    if employee:
        employee_id = connection.execute(
            text("INSERT INTO employees (first_name, last_name) VALUES ('A', 'Worker')")
        ).lastrowid
    connection.execute(
        text(
            "INSERT INTO company_payroll_jurisdictions "
            "(country_code, province_code, regulatory_scope, effective_from, effective_to) "
            "VALUES ('CA', 'ON', 'provincially_regulated', '2024-01-01', NULL)"
        )
    )
    return employee_id


def test_sqlite_migration_upgrade_preserves_company_open_range_index(tmp_path):
    from alembic import command

    database_path = tmp_path / "upgrade-open-range-index.sqlite"
    assert not database_path.exists()
    config = _migration_config(database_path)
    engine = None
    try:
        command.upgrade(config, _OLD_HEAD)
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            _seed_open_company_range(connection)
            assert _has_open_range_index(connection)
            assert _second_open_range_is_rejected(connection)
        engine.dispose()
        engine = None

        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            assert _has_open_range_index(connection)
            assert _second_open_range_is_rejected(connection)
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
        assert not database_path.exists()


def test_sqlite_migration_downgrade_preserves_company_open_range_index(tmp_path):
    from alembic import command

    database_path = tmp_path / "downgrade-open-range-index.sqlite"
    assert not database_path.exists()
    config = _migration_config(database_path)
    engine = None
    try:
        command.upgrade(config, _OLD_HEAD)
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            _seed_open_company_range(connection, employee=True)
        engine.dispose()
        engine = None
        command.upgrade(config, "head")

        # Isolate the downgrade rebuild from the independently tested upgrade
        # rebuild by restoring the exact legacy invariant before the downgrade.
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_company_payroll_jurisdiction_open_range "
                "ON company_payroll_jurisdictions ((1)) "
                "WHERE effective_to IS NULL"
            )
            assert _has_open_range_index(connection)
            assert _second_open_range_is_rejected(connection)
        engine.dispose()
        engine = None

        command.downgrade(config, _OLD_HEAD)

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            assert _has_open_range_index(connection)
            assert _second_open_range_is_rejected(connection)
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
        assert not database_path.exists()


def test_employee_province_api_requires_effective_company_mode_date(
    client, db_session
):
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction
    from app.models.payroll import Employee

    today = date.today()
    employee = Employee(first_name="Rae", last_name="API")
    db_session.add(employee)
    db_session.commit()
    endpoint = f"/api/settings/payroll-jurisdiction/employees/{employee.id}"

    no_mode = client.post(
        endpoint,
        json={
            "country_code": "CA",
            "province_code": "AB",
            "regulatory_scope": "provincially_regulated",
            "effective_from": today.isoformat(),
        },
    )
    mode_start = today + timedelta(days=10)
    scheduled_mode = client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": "CA", "effective_from": mode_start.isoformat()},
    )
    before_mode = client.post(
        endpoint,
        json={
            "country_code": "CA",
            "province_code": "ON",
            "regulatory_scope": "provincially_regulated",
            "effective_from": (mode_start - timedelta(days=1)).isoformat(),
        },
    )
    exact_mode_start = client.post(
        endpoint,
        json={
            "country_code": "CA",
            "province_code": "ON",
            "regulatory_scope": "provincially_regulated",
            "effective_from": mode_start.isoformat(),
        },
    )

    assert no_mode.status_code == 422, no_mode.text
    assert scheduled_mode.status_code == 201, scheduled_mode.text
    assert before_mode.status_code == 422, before_mode.text
    assert exact_mode_start.status_code == 201, exact_mode_start.text
    assert exact_mode_start.json()["effective_from"] == mode_start.isoformat()
    assignments = (
        db_session.query(EmployeePayrollJurisdiction)
        .filter_by(employee_id=employee.id)
        .all()
    )
    assert len(assignments) == 1
    assert assignments[0].effective_from == mode_start


def test_downgrade_refuses_employee_history_for_missing_employee(tmp_path):
    from alembic import command

    database_path = tmp_path / "orphan-employee-jurisdiction.sqlite"
    assert not database_path.exists()
    config = _migration_config(database_path)
    engine = None
    try:
        command.upgrade(config, _OLD_HEAD)
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            _seed_open_company_range(connection, employee=True)
        engine.dispose()
        engine = None
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
            connection.execute(
                text(
                    "INSERT INTO employee_payroll_jurisdictions "
                    "(employee_id, country_code, province_code, regulatory_scope, "
                    "effective_from, effective_to) "
                    "VALUES (999999, 'CA', 'AB', 'provincially_regulated', "
                    "'2025-01-01', NULL)"
                )
            )
            connection.commit()
        engine.dispose()
        engine = None

        try:
            command.downgrade(config, _OLD_HEAD)
        except RuntimeError as exc:
            assert "no matching employee" in str(exc).lower()
        else:
            pytest.fail("downgrade discarded an orphan employee jurisdiction row")

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            with engine.connect() as connection:
                inspector = inspect(connection)
                assert "employee_payroll_jurisdictions" in inspector.get_table_names()
                company_province = next(
                    column
                    for column in inspector.get_columns("company_payroll_jurisdictions")
                    if column["name"] == "province_code"
                )
                assert company_province["nullable"] is True
                assert connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one() == _MIGRATION_HEAD
                orphan = connection.execute(
                    text(
                        "SELECT employee_id, province_code, effective_from "
                        "FROM employee_payroll_jurisdictions WHERE employee_id = 999999"
                    )
                ).one()
                assert tuple(orphan) == (999999, "AB", "2025-01-01")
        finally:
            engine.dispose()
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
        assert not database_path.exists()


def test_downgrade_refuses_non_null_stub_jurisdiction_snapshot_without_ddl(
    tmp_path,
):
    from alembic import command

    database_path = tmp_path / "stub-jurisdiction-snapshot.sqlite"
    assert not database_path.exists()
    config = _migration_config(database_path)
    engine = None
    try:
        command.upgrade(config, _OLD_HEAD)
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            employee_id = _seed_open_company_range(connection, employee=True)
        engine.dispose()
        engine = None
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            pay_run_id = connection.execute(
                text(
                    "INSERT INTO pay_runs (period_start, period_end, pay_date) "
                    "VALUES ('2025-01-01', '2025-01-14', '2025-01-15')"
                )
            ).lastrowid
            connection.execute(
                text(
                    "INSERT INTO pay_stubs "
                    "(pay_run_id, employee_id, employee_jurisdiction_snapshot) "
                    "VALUES (:pay_run_id, :employee_id, '{}')"
                ),
                {"pay_run_id": pay_run_id, "employee_id": employee_id},
            )
        engine.dispose()
        engine = None

        def migration_state(connection):
            inspector = inspect(connection)
            stub_schema = tuple(
                (
                    column["name"],
                    str(column["type"]),
                    column["nullable"],
                    column["default"],
                )
                for column in inspector.get_columns("pay_stubs")
            )
            snapshot_present = any(
                column[0] == "employee_jurisdiction_snapshot"
                for column in stub_schema
            )
            snapshot_rows = (
                tuple(
                    tuple(row)
                    for row in connection.execute(
                        text(
                            "SELECT id, employee_jurisdiction_snapshot "
                            "FROM pay_stubs ORDER BY id"
                        )
                    ).all()
                )
                if snapshot_present
                else None
            )
            return {
                "employee_history": tuple(
                    tuple(row)
                    for row in connection.execute(
                        text(
                            "SELECT employee_id, country_code, province_code, "
                            "regulatory_scope, effective_from, effective_to, created_at "
                            "FROM employee_payroll_jurisdictions "
                            "ORDER BY employee_id, effective_from, id"
                        )
                    ).all()
                )
                if "employee_payroll_jurisdictions" in inspector.get_table_names()
                else None,
                "stub_schema": stub_schema,
                "stub_snapshot_rows": snapshot_rows,
                "company_history": tuple(
                    tuple(row)
                    for row in connection.execute(
                        text(
                            "SELECT id, country_code, province_code, regulatory_scope, "
                            "effective_from, effective_to, created_at "
                            "FROM company_payroll_jurisdictions "
                            "ORDER BY effective_from, id"
                        )
                    ).all()
                ),
                "company_indexes": tuple(
                    tuple(row)
                    for row in connection.execute(
                        text(
                            "SELECT name, sql FROM sqlite_master "
                            "WHERE type = 'index' "
                            "AND tbl_name = 'company_payroll_jurisdictions' "
                            "ORDER BY name"
                        )
                    ).all()
                ),
                "revision": connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one(),
            }

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.connect() as connection:
            before = migration_state(connection)
        engine.dispose()
        engine = None

        downgrade_error = None
        try:
            command.downgrade(config, _OLD_HEAD)
        except RuntimeError as exc:
            downgrade_error = exc

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.connect() as connection:
            after = migration_state(connection)
        engine.dispose()
        engine = None

        assert downgrade_error is not None, (
            "downgrade must reject a non-NULL employee snapshot before DDL; "
            f"got {downgrade_error!r}; before={before!r}; after={after!r}"
        )
        assert "snapshot" in str(downgrade_error).lower()
        assert after == before, (
            "downgrade failure changed employee history, pay-stub snapshot/schema, "
            "company history/index, or Alembic revision; "
            f"before={before!r}; after={after!r}"
        )
        assert before["stub_snapshot_rows"] == ((1, "{}"),)
        assert before["revision"] == _MIGRATION_HEAD
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
        database_path.with_name(database_path.name + "-wal").unlink(missing_ok=True)
        database_path.with_name(database_path.name + "-shm").unlink(missing_ok=True)
        assert not database_path.exists()
