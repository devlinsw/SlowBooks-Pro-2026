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
