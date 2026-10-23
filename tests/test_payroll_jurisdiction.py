"""Company-level Canadian country-mode boundary tests."""

import importlib.util
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest


def _payload(effective_from, **extra):
    return {
        "country_code": "CA",
        "effective_from": effective_from.isoformat(),
        **extra,
    }


def test_country_mode_is_unconfigured_until_company_sets_it(client):
    today = date.today().isoformat()
    response = client.get("/api/settings/payroll-jurisdiction")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "country_code": None,
        "effective_from": None,
        "effective_to": None,
        "server_today": today,
        "minimum_effective_from": today,
        "history": [],
    }


def test_company_country_activation_needs_no_province_and_is_effective_dated(client):
    today = date.today()
    effective_from = today + timedelta(days=20)
    created = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload(effective_from)
    )

    assert created.status_code == 201, created.text
    assert created.json() == {
        "country_code": "CA",
        "effective_from": effective_from.isoformat(),
        "effective_to": None,
    }
    current = client.get(
        "/api/settings/payroll-jurisdiction", params={"as_of": today.isoformat()}
    )
    active = client.get(
        "/api/settings/payroll-jurisdiction",
        params={"as_of": effective_from.isoformat()},
    )
    assert current.status_code == active.status_code == 200
    assert current.json()["country_code"] is None
    assert active.json()["country_code"] == "CA"
    assert "province_code" not in active.json()
    assert all("province_code" not in row for row in active.json()["history"])
    assert active.json()["minimum_effective_from"] is None


def test_company_api_forbids_a_company_wide_province_or_scope(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload(
            date.today(), province_code="ON", regulatory_scope="provincially_regulated"
        ),
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/settings/payroll-jurisdiction").json()["history"] == []


@pytest.mark.parametrize("country_code", ["US", "ca", "CAN"])
def test_company_country_mode_accepts_only_ca(client, country_code):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": country_code, "effective_from": date.today().isoformat()},
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/settings/payroll-jurisdiction").json()["history"] == []


def test_country_activation_is_prospective_and_not_retroactive_to_processed_payroll(
    client, db_session
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    effective_from = date.today() + timedelta(days=20)
    processed = PayRun(
        period_start=effective_from,
        period_end=effective_from + timedelta(days=6),
        pay_date=effective_from + timedelta(days=6),
        status=PayRunStatus.PROCESSED,
    )
    db_session.add(processed)
    db_session.commit()

    response = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload(effective_from)
    )

    assert response.status_code == 409, response.text
    assert db_session.query(PayrollJurisdiction).count() == 0
    assert db_session.query(PayRun).one().status is PayRunStatus.PROCESSED


def test_country_activation_rejects_processed_period_intersecting_effective_date(
    client, db_session
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    today = date.today()
    effective_from = today + timedelta(days=4)
    processed = PayRun(
        period_start=today,
        period_end=today + timedelta(days=7),
        pay_date=today + timedelta(days=3),
        status=PayRunStatus.PROCESSED,
    )
    db_session.add(processed)
    db_session.commit()

    response = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload(effective_from)
    )

    assert response.status_code == 409, response.text
    assert db_session.query(PayrollJurisdiction).count() == 0


def test_country_activation_after_pre_effective_processed_run_is_allowed(
    client, db_session
):
    from app.models.payroll import PayRun, PayRunStatus
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    effective_from = date.today() + timedelta(days=20)
    db_session.add(
        PayRun(
            period_start=effective_from - timedelta(days=7),
            period_end=effective_from - timedelta(days=1),
            pay_date=effective_from - timedelta(days=1),
            status=PayRunStatus.PROCESSED,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload(effective_from)
    )

    assert response.status_code == 201, response.text
    assert db_session.query(PayrollJurisdiction).one().province_code is None
    assert db_session.query(PayRun).one().status is PayRunStatus.PROCESSED


def test_database_enforces_one_open_company_country_mode_range(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.payroll_jurisdiction import PayrollJurisdiction

    today = date.today()
    db_session.add_all(
        [
            PayrollJurisdiction(
                country_code="CA",
                province_code=None,
                regulatory_scope="provincially_regulated",
                effective_from=today,
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code=None,
                regulatory_scope="provincially_regulated",
                effective_from=today + timedelta(days=1),
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_company_record_scope_remains_required_in_storage(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.payroll_jurisdiction import PayrollJurisdiction

    db_session.add(
        PayrollJurisdiction(country_code="CA", effective_from=date.today())
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_legacy_company_province_remains_stored_but_is_masked_from_new_readers(
    client, db_session
):
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.services.payroll_jurisdiction_service import (
        resolve_company_payroll_jurisdiction,
    )

    legacy = PayrollJurisdiction(
        country_code="CA",
        province_code="AB",
        regulatory_scope="provincially_regulated",
        effective_from=date.today(),
    )
    db_session.add(legacy)
    db_session.commit()

    resolved = resolve_company_payroll_jurisdiction(db_session, date.today())
    response = client.get("/api/settings/payroll-jurisdiction")

    assert resolved is not None
    assert resolved.country_code == "CA"
    assert resolved.province_code is None
    assert response.status_code == 200, response.text
    assert "province_code" not in response.json()
    assert "province_code" not in response.json()["history"][0]
    assert db_session.query(PayrollJurisdiction).one().province_code == "AB"


def test_malformed_company_effective_date_is_refused(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json={"country_code": "CA", "effective_from": "2026-02-30"},
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/settings/payroll-jurisdiction").json()["history"] == []


def _freeze_jurisdiction_today(monkeypatch, current_date):
    from app.routes import payroll_jurisdiction as route
    from app.services import payroll_jurisdiction_service

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return current_date

    monkeypatch.setattr(route, "date", FrozenDate)
    monkeypatch.setattr(payroll_jurisdiction_service, "date", FrozenDate)


def test_country_api_uses_server_today_for_future_activation(client, monkeypatch):
    server_today = date(2030, 6, 15)
    _freeze_jurisdiction_today(monkeypatch, server_today)
    future_start = server_today + timedelta(days=20)

    empty = client.get("/api/settings/payroll-jurisdiction")
    created = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload(future_start)
    )
    state = client.get("/api/settings/payroll-jurisdiction")

    assert empty.status_code == 200, empty.text
    assert created.status_code == 201, created.text
    assert state.status_code == 200, state.text
    assert empty.json()["server_today"] == server_today.isoformat()
    assert empty.json()["minimum_effective_from"] == server_today.isoformat()
    assert state.json()["server_today"] == server_today.isoformat()
    assert state.json()["minimum_effective_from"] is None


def test_date_max_is_allowed_as_terminal_country_activation(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload(date.max)
    )
    state = client.get("/api/settings/payroll-jurisdiction")

    assert response.status_code == 201, response.text
    assert state.status_code == 200, state.text
    assert state.json()["minimum_effective_from"] is None
    assert state.json()["history"][0]["effective_from"] == date.max.isoformat()


def test_unconfigured_company_can_activate_on_date_max_when_today_is_date_max(
    client, monkeypatch
):
    _freeze_jurisdiction_today(monkeypatch, date.max)

    empty = client.get("/api/settings/payroll-jurisdiction")
    response = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload(date.max)
    )

    assert empty.status_code == 200, empty.text
    assert empty.json()["minimum_effective_from"] == date.max.isoformat()
    assert response.status_code == 201, response.text


def test_settings_ui_shows_country_boundary_and_incomplete_employee_setup():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "static" / "js" / "settings.js").read_text(
        encoding="utf-8"
    )

    assert "Payroll Country Mode" in source
    assert "prevents concurrent U.S. payroll" in source
    assert "Province of employment must be configured per employee" in source
    assert "Canadian payroll calculations" in source
    assert "One Canadian payroll province applies to this entire company" not in source
    assert "payroll-jurisdiction-province" not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_settings_ui_posts_country_mode_without_province_or_scope():
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        ["node", str(root / "tests" / "js" / "payroll_jurisdiction_probe.js")],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    state = json.loads(out.stdout)

    assert state["posted_country"] == "CA"
    assert state["posted_effective_from"] == "2031-02-03"
    assert "province_code" not in state["posted_payload"]
    assert "regulatory_scope" not in state["posted_payload"]
    assert state["minimum_is_rendered_as_min_and_value"] is True
    assert state["maximum_is_rendered"] is True


def test_payroll_jurisdiction_migration_upgrade_downgrade_reupgrade_has_no_scope_default(
    tmp_path,
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    root = Path(__file__).resolve().parents[1]
    migration_path = (
        root
        / "migrations"
        / "versions"
        / "f1b2c3d4e5f6_company_payroll_jurisdictions.py"
    )
    spec = importlib.util.spec_from_file_location(
        "company_payroll_jurisdictions_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'legacy-company-jurisdiction.db').as_posix()}"
    )

    with engine.begin() as connection:
        operations = MigrationContext.configure(connection)
        with Operations.context(operations):
            migration.upgrade()
        columns = inspect(connection).get_columns("company_payroll_jurisdictions")
        scope = next(column for column in columns if column["name"] == "regulatory_scope")
        assert scope["nullable"] is False
        assert scope["default"] is None
        with Operations.context(operations):
            migration.downgrade()
        assert "company_payroll_jurisdictions" not in inspect(connection).get_table_names()
        with Operations.context(operations):
            migration.upgrade()
        columns = inspect(connection).get_columns("company_payroll_jurisdictions")
        scope = next(column for column in columns if column["name"] == "regulatory_scope")
        assert scope["nullable"] is False
        assert scope["default"] is None
    engine.dispose()


def test_locked_file_backed_sqlite_returns_retryable_conflict_not_500(client, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import get_db
    from app.main import app
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction
    from app.models.payroll import Employee
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'locked-country-mode.db').as_posix()}",
        connect_args={"timeout": 0},
    )
    Employee.__table__.create(engine)
    PayrollJurisdiction.__table__.create(engine)
    EmployeePayrollJurisdiction.__table__.create(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = file_backed_db
    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)
    lock = engine.connect()
    try:
        lock.exec_driver_sql("BEGIN EXCLUSIVE")
        response = request_client.post(
            "/api/settings/payroll-jurisdiction", json=_payload(date.today())
        )
    finally:
        lock.rollback()
        lock.close()
        request_client.close()
        engine.dispose()

    assert response.status_code == 409, response.text
    assert response.headers.get("retry-after") == "1"
    assert "database is busy" in response.json()["detail"].lower()


def test_simultaneous_country_mode_posts_preserve_one_history(client, monkeypatch, tmp_path):
    from threading import Barrier, Lock, Thread

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import get_db
    from app.main import app
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction
    from app.models.payroll import Employee, PayRun
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.routes import payroll_jurisdiction as jurisdiction_routes

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrent-country-mode.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )
    Employee.__table__.create(engine)
    PayrollJurisdiction.__table__.create(engine)
    EmployeePayrollJurisdiction.__table__.create(engine)
    PayRun.__table__.create(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = file_backed_db
    service_entry = Barrier(2)
    result_lock = Lock()
    responses = []
    worker_errors = []
    original_add = jurisdiction_routes.add_company_payroll_jurisdiction

    def add_after_both_posts_enter_service(db, **kwargs):
        service_entry.wait(timeout=10)
        return original_add(db, **kwargs)

    monkeypatch.setattr(
        jurisdiction_routes,
        "add_company_payroll_jurisdiction",
        add_after_both_posts_enter_service,
    )

    def post_country_mode():
        request_client = None
        try:
            request_client = TestClient(app, raise_server_exceptions=False)
            request_client.cookies.update(client.cookies)
            response = request_client.post(
                "/api/settings/payroll-jurisdiction", json=_payload(date.today())
            )
            with result_lock:
                responses.append(response)
        except BaseException as exc:
            with result_lock:
                worker_errors.append(exc)
        finally:
            if request_client is not None:
                request_client.close()

    threads = [Thread(target=post_country_mode, daemon=True) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads), "POST worker timed out"
        assert worker_errors == []
        assert len(responses) == 2
        assert sorted(response.status_code for response in responses) == [201, 409]

        created = next(response for response in responses if response.status_code == 201)
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["detail"] in {
            "Canadian country mode is already configured or scheduled.",
            "Payroll jurisdiction database is busy; retry the request.",
        }
        with Session() as persisted_session:
            stored = persisted_session.query(PayrollJurisdiction).one()
            assert stored.country_code == "CA"
            assert stored.province_code is None
            assert created.json() == {
                "country_code": "CA",
                "effective_from": stored.effective_from.isoformat(),
                "effective_to": None,
            }
        history_client = TestClient(app, raise_server_exceptions=False)
        history_client.cookies.update(client.cookies)
        try:
            history_response = history_client.get("/api/settings/payroll-jurisdiction")
        finally:
            history_client.close()
        assert history_response.status_code == 200, history_response.text
        assert len(history_response.json()["history"]) == 1
        assert "province_code" not in history_response.json()["history"][0]
    finally:
        service_entry.abort()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=15)
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()


def test_expected_company_timeline_uniqueness_violation_maps_to_conflict(
    db_session, monkeypatch
):
    import sqlite3

    from sqlalchemy.exc import IntegrityError

    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.services.payroll_jurisdiction_service import (
        PayrollJurisdictionConflict,
        add_company_payroll_jurisdiction,
    )

    def commit_with_expected_unique_violation():
        raise IntegrityError(
            "INSERT INTO company_payroll_jurisdictions",
            {},
            sqlite3.IntegrityError(
                "UNIQUE constraint failed: company_payroll_jurisdictions.effective_from"
            ),
        )

    monkeypatch.setattr(db_session, "commit", commit_with_expected_unique_violation)

    with pytest.raises(PayrollJurisdictionConflict, match="already configured"):
        add_company_payroll_jurisdiction(
            db_session, country_code="CA", effective_from=date.today()
        )
    assert db_session.query(PayrollJurisdiction).count() == 0


def test_unrelated_check_constraint_error_is_not_mislabeled_as_timeline_conflict(
    db_session, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.services.payroll_jurisdiction_service import add_company_payroll_jurisdiction

    commit = db_session.commit

    def commit_with_invalid_scope():
        pending = next(item for item in db_session.new if isinstance(item, PayrollJurisdiction))
        pending.regulatory_scope = "federally_regulated"
        commit()

    monkeypatch.setattr(db_session, "commit", commit_with_invalid_scope)

    with pytest.raises(IntegrityError, match="ck_company_payroll_jurisdiction_scope"):
        add_company_payroll_jurisdiction(
            db_session, country_code="CA", effective_from=date.today()
        )
    assert db_session.query(PayrollJurisdiction).count() == 0


def test_country_mode_response_is_snapshotted_before_post_commit_database_lock(
    client, tmp_path
):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session as OrmSession, sessionmaker

    from app.database import get_db
    from app.main import app
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction
    from app.models.payroll import Employee, PayRun
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'post-commit-country-mode.db').as_posix()}",
        connect_args={"timeout": 0},
    )
    Employee.__table__.create(engine)
    PayrollJurisdiction.__table__.create(engine)
    EmployeePayrollJurisdiction.__table__.create(engine)
    PayRun.__table__.create(engine)

    class JurisdictionSession(OrmSession):
        pass

    Session = sessionmaker(
        bind=engine,
        class_=JurisdictionSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=True,
    )
    lock = engine.connect()
    lock_acquired = []

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def lock_database_after_commit(session):
        if session.get_bind() is engine:
            lock.exec_driver_sql("BEGIN EXCLUSIVE")
            lock_acquired.append(True)

    event.listen(JurisdictionSession, "after_commit", lock_database_after_commit)
    app.dependency_overrides[get_db] = file_backed_db
    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)
    today = date.today()
    try:
        response = request_client.post(
            "/api/settings/payroll-jurisdiction", json=_payload(today)
        )
    finally:
        lock.rollback()
        lock.close()
        event.remove(JurisdictionSession, "after_commit", lock_database_after_commit)
        request_client.close()
        engine.dispose()

    assert lock_acquired == [True]
    assert response.status_code == 201, response.text
    assert response.json() == {
        "country_code": "CA",
        "effective_from": today.isoformat(),
        "effective_to": None,
    }


def test_missing_country_mode_table_fails_closed_with_unavailable_response(
    client, tmp_path
):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'missing-country-mode-table.db').as_posix()}",
        connect_args={"timeout": 0},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = file_backed_db
    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)
    try:
        response = request_client.post(
            "/api/settings/payroll-jurisdiction", json=_payload(date.today())
        )
    finally:
        request_client.close()
        engine.dispose()

    assert response.status_code == 503, response.text


def test_country_mode_state_derives_active_record_from_one_history_snapshot(monkeypatch):
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.routes.payroll_jurisdiction import _company_state
    from app.services import payroll_jurisdiction_service

    today = date.today()
    record = PayrollJurisdiction(
        country_code="CA",
        province_code="AB",
        regulatory_scope="provincially_regulated",
        effective_from=today,
    )
    query_count = 0

    def load_history(_db, *, lock=False):
        nonlocal query_count
        query_count += 1
        return [record]

    monkeypatch.setattr(payroll_jurisdiction_service, "_ordered_history", load_history)
    state = _company_state(object(), today)

    assert state["country_code"] == "CA"
    assert state["effective_from"] == today.isoformat()
    assert "province_code" not in state
    assert query_count == 1


def test_unrelated_sqlite_operational_error_is_not_mislabeled_as_busy(
    client, tmp_path
):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'missing-country-table.db').as_posix()}",
        connect_args={"timeout": 0},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = file_backed_db
    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)
    try:
        response = request_client.post(
            "/api/settings/payroll-jurisdiction", json=_payload(date.today())
        )
    finally:
        request_client.close()
        engine.dispose()

    assert response.status_code == 503, response.text
