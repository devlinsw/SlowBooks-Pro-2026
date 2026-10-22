"""Disposable PostgreSQL coverage for jurisdiction scheduling concurrency.

Set SLOWBOOKS_TEST_POSTGRES_URL to a disposable loopback PostgreSQL database to
run this test. It creates and drops a unique schema; the default suite skips it.
"""

import os
import threading
import time
import uuid
from datetime import date, timedelta
from threading import current_thread

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.payroll_jurisdiction import PayrollJurisdiction
from app.services import payroll_jurisdiction_service
from app.services.payroll_jurisdiction_service import (
    add_company_payroll_jurisdiction,
)


@pytest.mark.skipif(
    not os.getenv("SLOWBOOKS_TEST_POSTGRES_URL"),
    reason="requires an explicit disposable PostgreSQL test URL",
)
def test_read_committed_schedule_refreshes_history_after_row_lock_wait(monkeypatch):
    database_url = os.environ["SLOWBOOKS_TEST_POSTGRES_URL"]
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        pytest.fail("SLOWBOOKS_TEST_POSTGRES_URL must use PostgreSQL")
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL concurrency test is restricted to loopback hosts")

    schema = f"slowbooks_jurisdiction_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    schema_created = False
    engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True

        engine = create_engine(
            database_url,
            isolation_level="READ COMMITTED",
            pool_size=5,
            max_overflow=0,
        )

        @event.listens_for(engine, "connect")
        def set_test_schema(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.close()

        PayrollJurisdiction.__table__.create(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=True)

        @event.listens_for(engine, "before_cursor_execute")
        def observe_second_writer_lock(
            _connection, _cursor, statement, _parameters, _context, _many
        ):
            if (
                current_thread().name == "schedule-B"
                and "LOCK TABLE COMPANY_PAYROLL_JURISDICTIONS" in statement.upper()
            ):
                second_writer_entered_lock.set()

        today = date.today()
        first_change = today + timedelta(days=30)
        later_change = today + timedelta(days=60)
        with Session() as session:
            add_company_payroll_jurisdiction(
                session,
                country_code="CA",
                province_code="AB",
                effective_from=today,
                regulatory_scope="provincially_regulated",
            )

        original_ordered_history = payroll_jurisdiction_service._ordered_history
        first_writer_locked = threading.Event()
        release_first_writer = threading.Event()
        second_writer_entered_lock = threading.Event()
        result_lock = threading.Lock()
        backend_pids = {}
        results = {}
        errors = {}

        def ordered_history_with_barrier(session, *, lock=False):
            history = original_ordered_history(session, lock=lock)
            if lock and current_thread().name == "schedule-A":
                first_writer_locked.set()
                if not release_first_writer.wait(timeout=15):
                    raise TimeoutError("timed out waiting to release schedule A")
            return history

        monkeypatch.setattr(
            payroll_jurisdiction_service,
            "_ordered_history",
            ordered_history_with_barrier,
        )

        def schedule(name, province, effective_from):
            try:
                with Session() as session:
                    pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                    with result_lock:
                        backend_pids[name] = pid
                    result = add_company_payroll_jurisdiction(
                        session,
                        country_code="CA",
                        province_code=province,
                        effective_from=effective_from,
                        regulatory_scope="provincially_regulated",
                    )
                    with result_lock:
                        results[name] = result
            except BaseException as exc:
                with result_lock:
                    errors[name] = exc

        writer_a = threading.Thread(
            name="schedule-A", target=schedule, args=("A", "ON", first_change)
        )
        writer_b = threading.Thread(
            name="schedule-B", target=schedule, args=("B", "BC", later_change)
        )
        try:
            writer_a.start()
            assert first_writer_locked.wait(timeout=10), "schedule A did not acquire the transaction lock"
            writer_b.start()
            assert second_writer_entered_lock.wait(timeout=10), "schedule B did not attempt the table lock"

            with result_lock:
                second_pid = backend_pids["B"]
            lock_wait = None
            deadline = time.monotonic() + 10
            with admin_engine.connect() as observer:
                while time.monotonic() < deadline:
                    lock_wait = observer.execute(
                        text(
                            "SELECT wait_event_type, wait_event, query "
                            "FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": second_pid},
                    ).mappings().one_or_none()
                    if lock_wait and lock_wait["wait_event_type"] == "Lock":
                        break
                    time.sleep(0.025)
            assert lock_wait is not None, "schedule B backend disappeared while waiting"
            assert lock_wait["wait_event_type"] == "Lock", (
                "schedule B was not blocked in PostgreSQL on schedule A's table lock: "
                f"{dict(lock_wait)}"
            )
            assert "company_payroll_jurisdictions" in lock_wait["query"]
        finally:
            release_first_writer.set()
            writer_a.join(timeout=15)
            if writer_b.ident is not None:
                writer_b.join(timeout=15)

        assert not writer_a.is_alive(), "schedule A did not finish"
        assert not writer_b.is_alive(), "schedule B did not finish"
        assert errors == {}, f"concurrent schedules failed: {errors!r}"
        assert set(results) == {"A", "B"}

        with Session() as session:
            history = (
                session.query(PayrollJurisdiction)
                .order_by(PayrollJurisdiction.effective_from)
                .all()
            )
            assert len(history) == 3
            assert [item.province_code for item in history] == ["AB", "ON", "BC"]
            assert [item.effective_from for item in history] == [
                today,
                first_change,
                later_change,
            ]
            assert [item.effective_to for item in history] == [
                first_change - timedelta(days=1),
                later_change - timedelta(days=1),
                None,
            ]
            assert sum(item.effective_to is None for item in history) == 1
            assert all(
                previous.effective_to + timedelta(days=1) == current.effective_from
                for previous, current in zip(history, history[1:])
            )
    finally:
        if engine is not None:
            engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("SLOWBOOKS_TEST_POSTGRES_URL"),
    reason="requires an explicit disposable PostgreSQL test URL",
)
def test_benefit_seed_waits_for_initial_jurisdiction_activation(monkeypatch, client):
    """The seed route waits on PostgreSQL's table lock and re-reads Canada."""
    from fastapi.testclient import TestClient
    from starlette.requests import HTTPConnection

    from app.database import Base, get_db
    from app.main import app
    from app.models.accounts import Account
    from app.models.benefits import BenefitCode
    from app.models import (  # noqa: F401 - load all metadata before create_all
        accounts,
        attachments,
        audit,
        auth,
        bank_accounts,
        bank_rules,
        banking,
        backups,
        benefits,
        bills,
        budgets,
        companies,
        contacts,
        credit_memos,
        deductions,
        document_audit,
        email_log,
        email_templates,
        estimates,
        hr,
        in_kind,
        invoices,
        items,
        payments,
        payroll,
        portal_access,
        pto,
        purchase_orders,
        qbo_mapping,
        recurring,
        request_keys,
        reseller_permit,
        settings,
        tax,
        time_entries,
        transactions,
        vendor_credits,
    )
    from app.routes import benefits as benefit_routes
    from app.services import payroll_jurisdiction_service
    from sqlalchemy.orm import Session as SessionClass

    database_url = os.environ["SLOWBOOKS_TEST_POSTGRES_URL"]
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        pytest.fail("SLOWBOOKS_TEST_POSTGRES_URL must use PostgreSQL")
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL concurrency test is restricted to loopback hosts")

    schema = f"slowbooks_benefit_seed_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    schema_created = False
    engine = None
    previous_override = app.dependency_overrides.get(get_db)
    results = {}
    errors = {}
    backend_pids = {}
    commits = []
    state_lock = threading.Lock()
    activation_history_read = threading.Event()
    release_activation = threading.Event()
    seed_lock_attempted = threading.Event()
    seed_resolved = threading.Event()
    writer_done = threading.Event()
    seed_done = threading.Event()
    writer_thread = None
    seed_thread = None
    registered_listeners = []

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        engine = create_engine(
            database_url,
            isolation_level="READ COMMITTED",
            pool_size=5,
            max_overflow=0,
        )

        @event.listens_for(engine, "connect")
        def set_test_schema(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.close()

        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=True)

        def independent_db(request: HTTPConnection = None):  # type: ignore[assignment]
            session = Session()
            path = request.url.path if request is not None else ""
            role = "jurisdiction" if path == "/api/settings/payroll-jurisdiction" else "benefit-seed"
            session.info["pg_race_role"] = role
            try:
                pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                with state_lock:
                    backend_pids[role] = pid
                yield session
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        app.dependency_overrides[get_db] = independent_db

        @event.listens_for(SessionClass, "after_begin")
        def tag_connection(session, _transaction, connection):
            connection.info["pg_race_role"] = session.info.get("pg_race_role")

        registered_listeners.append((SessionClass, "after_begin", tag_connection))

        @event.listens_for(engine, "before_cursor_execute")
        def observe_seed_lock(connection, _cursor, statement, _parameters, _context, _many):
            if (
                connection.info.get("pg_race_role") == "benefit-seed"
                and "LOCK TABLE COMPANY_PAYROLL_JURISDICTIONS" in statement.upper()
            ):
                seed_lock_attempted.set()

        registered_listeners.append(
            (engine, "before_cursor_execute", observe_seed_lock)
        )

        @event.listens_for(SessionClass, "after_commit")
        def record_commit(session):
            role = session.info.get("pg_race_role")
            if role in {"jurisdiction", "benefit-seed"}:
                with state_lock:
                    commits.append(role)

        registered_listeners.append((SessionClass, "after_commit", record_commit))

        original_history = payroll_jurisdiction_service._ordered_history

        def pause_activation_after_lock(db, *, lock=False):
            history = original_history(db, lock=lock)
            if lock and db.info.get("pg_race_role") == "jurisdiction":
                activation_history_read.set()
                if not release_activation.wait(timeout=20):
                    raise TimeoutError("activation writer was not released")
            return history

        monkeypatch.setattr(
            payroll_jurisdiction_service, "_ordered_history", pause_activation_after_lock
        )
        original_resolve = benefit_routes.resolve_company_payroll_jurisdiction

        def observe_seed_resolution(db, as_of):
            resolved = original_resolve(db, as_of)
            if db.info.get("pg_race_role") == "benefit-seed":
                seed_resolved.set()
            return resolved

        monkeypatch.setattr(
            benefit_routes, "resolve_company_payroll_jurisdiction", observe_seed_resolution
        )

        def send_jurisdiction():
            try:
                with TestClient(app, raise_server_exceptions=False) as request_client:
                    request_client.cookies.update(client.cookies)
                    results["jurisdiction"] = request_client.post(
                        "/api/settings/payroll-jurisdiction",
                        json={
                            "country_code": "CA",
                            "province_code": "ON",
                            "regulatory_scope": "provincially_regulated",
                            "effective_from": date.today().isoformat(),
                        },
                    )
            except BaseException as exc:
                errors["jurisdiction"] = exc
            finally:
                writer_done.set()

        def send_seed():
            try:
                with TestClient(app, raise_server_exceptions=False) as request_client:
                    request_client.cookies.update(client.cookies)
                    results["benefit-seed"] = request_client.post(
                        "/api/benefits/codes/seed-standard"
                    )
            except BaseException as exc:
                errors["benefit-seed"] = exc
            finally:
                seed_done.set()

        writer_thread = threading.Thread(
            name="jurisdiction-writer", target=send_jurisdiction, daemon=True
        )
        seed_thread = threading.Thread(name="benefit-seed", target=send_seed, daemon=True)
        writer_thread.start()
        assert activation_history_read.wait(timeout=15), (
            "activation writer did not hold the jurisdiction table lock"
        )
        seed_thread.start()
        assert seed_lock_attempted.wait(timeout=15), (
            "benefit seed route did not attempt the shared jurisdiction table lock"
        )
        assert not seed_resolved.is_set(), (
            "benefit seed resolved jurisdiction before acquiring the shared lock"
        )

        with state_lock:
            seed_pid = backend_pids["benefit-seed"]
        lock_wait = None
        deadline = time.monotonic() + 15
        with admin_engine.connect() as observer:
            while time.monotonic() < deadline:
                lock_wait = observer.execute(
                    text(
                        "SELECT wait_event_type, wait_event, query "
                        "FROM pg_stat_activity WHERE pid = :pid"
                    ),
                    {"pid": seed_pid},
                ).mappings().one_or_none()
                if lock_wait and lock_wait["wait_event_type"] == "Lock":
                    break
                time.sleep(0.025)
        assert lock_wait is not None, "benefit seed backend disappeared while waiting"
        assert lock_wait["wait_event_type"] == "Lock", (
            "benefit seed was not blocked by PostgreSQL's jurisdiction table lock"
        )
        assert "company_payroll_jurisdictions" in lock_wait["query"].lower()
        assert not seed_done.is_set(), "benefit seed completed before activation committed"

        release_activation.set()
        writer_thread.join(timeout=20)
        seed_thread.join(timeout=20)
        assert not writer_thread.is_alive(), "activation request did not finish"
        assert not seed_thread.is_alive(), "benefit seed request did not finish"
        assert not errors, "a PostgreSQL race request raised an exception"
        assert results["jurisdiction"].status_code == 201
        assert results["benefit-seed"].status_code == 422
        assert seed_resolved.is_set(), "benefit seed did not re-read jurisdiction after waiting"
        assert commits == ["jurisdiction"]

        with Session() as verify:
            configured_country = verify.execute(
                text("SELECT country_code FROM company_payroll_jurisdictions")
            ).scalar_one()
            assert configured_country == "CA"
            assert verify.query(Account).count() == 0
            assert verify.query(BenefitCode).count() == 0
    finally:
        release_activation.set()
        for worker in (writer_thread, seed_thread):
            if worker is not None and worker.ident is not None:
                worker.join(timeout=20)
        for target, identifier, listener in reversed(registered_listeners):
            event.remove(target, identifier, listener)
        if engine is not None:
            engine.dispose()
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
