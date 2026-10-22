"""Real competing-transaction coverage for jurisdiction activation guards.

These tests use an independent file-backed SQLite database and actual HTTP
routes. The barriers hold one transaction after its real jurisdiction read,
then start the competing write in the historical check/commit race window.
"""

from datetime import date
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def _employee_payload():
    return {
        "first_name": "Race",
        "last_name": "Guard",
        "pay_type": "hourly",
        "pay_rate": 25,
        "filing_status": "single",
        "work_state": "WA",
        "ssn_last_four": "1234",
    }


def _jurisdiction_payload():
    return {
        "country_code": "CA",
        "province_code": "ON",
        "regulatory_scope": "provincially_regulated",
        "effective_from": date.today().isoformat(),
    }


def _guarded_request(client, kind, employee_id, token):
    if kind == "admin-create":
        return client.post("/api/employees", json=_employee_payload())
    if kind == "admin-update":
        return client.put(
            f"/api/employees/{employee_id}",
            json={"filing_status": "married", "pay_rate": 99},
        )
    if kind == "portal-cookie":
        client.cookies.set("slowbooks_portal", token, path="/portal")
        return client.post(
            "/portal/profile",
            data={"filing_status": "married", "state": "CA", "address1": "New"},
        )
    if kind == "portal-token":
        return client.post(
            f"/portal/{token}/profile",
            data={"filing_status": "married", "state": "CA", "address1": "New"},
        )
    if kind == "pay-run":
        today = date.today().isoformat()
        return client.post(
            "/api/payroll",
            json={
                "period_start": today,
                "period_end": today,
                "pay_date": today,
                "stubs": [
                    {
                        "employee_id": employee_id,
                        "gross_override": 1000,
                        "hours": 0,
                        "use_time_entries": False,
                    }
                ],
            },
        )
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    ["admin-create", "admin-update", "portal-cookie", "portal-token", "pay-run"],
)
@pytest.mark.parametrize("winner", ["guarded", "jurisdiction"])
def test_guarded_write_and_initial_jurisdiction_activation_serialize(
    client, monkeypatch, tmp_path, kind, winner
):
    """Each real guarded route must serialize against empty-history activation.

    If the guarded route wins, it commits before activation. If activation wins,
    the route sees Canada and refuses before employee/profile/pay-run writes.
    """
    from app.database import Base, get_db, enable_sqlite_tuning
    from app.main import app
    from app.models.payroll import Employee, FilingStatus, PayRun, PayStub
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.models.portal_access import PortalAccess
    from app.models.hr import OnboardingTask
    from app.services import payroll_jurisdiction_service
    from app.models import (  # noqa: F401 - ensure every metadata table is loaded
        accounts,
        attachments,
        audit,
        auth,
        bank_accounts,
        bank_rules,
        banking,
        backups,
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

    from app.routes import employees as employee_routes
    from app.routes import payroll_jurisdiction as jurisdiction_routes
    from app.routes import portal as portal_routes
    from app.routes.payroll import runs as run_routes
    from sqlalchemy.orm import Session as SessionClass
    from starlette.requests import HTTPConnection

    database_path = tmp_path / f"jurisdiction-guard-{kind}-{winner}.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    enable_sqlite_tuning(engine)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    token = "race-test-portal-token"
    with SessionFactory() as seed:
        employee = Employee(
            first_name="Race",
            last_name="Guard",
            pay_type="hourly",
            pay_rate=25,
            filing_status=FilingStatus.SINGLE,
            work_state="WA",
            portal_token=token,
        )
        seed.add(employee)
        seed.commit()
        employee_id = employee.id

    def independent_db(request: HTTPConnection = None):  # type: ignore[assignment]
        session = SessionFactory()
        path = request.url.path if request is not None else ""
        role = "jurisdiction" if path == "/api/settings/payroll-jurisdiction" else "guarded"
        session.info["race_role"] = role
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = independent_db

    profile_read = Event()
    release_profile = Event()
    writer_history_read = Event()
    release_writer = Event()
    writer_service_started = Event()
    profile_lock_attempted = Event()
    writer_lock_attempted = Event()
    profile_first_sql_attempted = Event()
    profile_done = Event()
    writer_done = Event()
    results = {}
    thread_errors = {}
    commit_order = []
    first_sql_by_role = {}

    @event.listens_for(SessionClass, "after_begin")
    def _tag_connection(session, _transaction, connection):
        connection.info["race_role"] = session.info.get("race_role")

    @event.listens_for(engine, "before_cursor_execute")
    def _observe_lock_attempt(connection, _cursor, statement, _parameters, _context, _many):
        upper = statement.upper()
        role = connection.info.get("race_role")
        if role in {"guarded", "jurisdiction"} and role not in first_sql_by_role:
            first_sql_by_role[role] = statement
            if role == "guarded":
                profile_first_sql_attempted.set()
        is_lock = (
            "UPDATE COMPANY_PAYROLL_JURISDICTIONS" in upper
            or "LOCK TABLE COMPANY_PAYROLL_JURISDICTIONS" in upper
            or "BEGIN IMMEDIATE" in upper
            or "PG_ADVISORY_XACT_LOCK" in upper
        )
        if is_lock and role == "guarded":
            profile_lock_attempted.set()
        elif is_lock and role == "jurisdiction":
            writer_lock_attempted.set()

    @event.listens_for(SessionClass, "after_commit")
    def _record_commit(session):
        role = session.info.get("race_role")
        if role in {"guarded", "jurisdiction"}:
            commit_order.append(role)

    original_history = payroll_jurisdiction_service._ordered_history

    def synchronized_history(db, *, lock=False):
        history = original_history(db, lock=lock)
        if lock and db.info.get("race_role") == "jurisdiction" and winner == "jurisdiction":
            writer_history_read.set()
            if not release_writer.wait(timeout=15):
                raise TimeoutError("jurisdiction writer was not released")
        return history

    monkeypatch.setattr(payroll_jurisdiction_service, "_ordered_history", synchronized_history)

    # The route module holds the service function as an imported alias.
    original_add = jurisdiction_routes.add_company_payroll_jurisdiction

    def start_writer(*args, **kwargs):
        writer_service_started.set()
        return original_add(*args, **kwargs)

    monkeypatch.setattr(jurisdiction_routes, "add_company_payroll_jurisdiction", start_writer)

    route_module = {
        "admin-create": employee_routes,
        "admin-update": employee_routes,
        "portal-cookie": portal_routes,
        "portal-token": portal_routes,
        "pay-run": run_routes,
    }[kind]
    original_resolve = route_module.resolve_company_payroll_jurisdiction

    def pause_after_real_resolution(db, as_of):
        result = original_resolve(db, as_of)
        if db.info.get("race_role") == "guarded":
            profile_read.set()
            if not release_profile.wait(timeout=15):
                raise TimeoutError("guarded request was not released")
        return result

    monkeypatch.setattr(route_module, "resolve_company_payroll_jurisdiction", pause_after_real_resolution)

    def send_guarded_request():
        try:
            with TestClient(app, raise_server_exceptions=False) as request_client:
                request_client.cookies.update(client.cookies)
                response = _guarded_request(request_client, kind, employee_id, token)
                results["guarded"] = response
        except BaseException as exc:
            thread_errors["guarded"] = exc
        finally:
            profile_done.set()

    def send_jurisdiction_request():
        try:
            with TestClient(app, raise_server_exceptions=False) as request_client:
                request_client.cookies.update(client.cookies)
                response = request_client.post(
                    "/api/settings/payroll-jurisdiction", json=_jurisdiction_payload()
                )
                results["jurisdiction"] = response
        except BaseException as exc:
            thread_errors["jurisdiction"] = exc
        finally:
            writer_done.set()

    guarded_thread = Thread(name="guarded-request", target=send_guarded_request, daemon=True)
    writer_thread = Thread(name="jurisdiction-writer", target=send_jurisdiction_request, daemon=True)
    try:
        if winner == "guarded":
            guarded_thread.start()
            assert profile_read.wait(timeout=10), "guarded route did not resolve real empty history"
            writer_thread.start()
            assert writer_service_started.wait(timeout=10), "jurisdiction writer did not enter service"
            writer_lock_attempted.wait(timeout=2)
            writer_finished_before_guard = writer_done.wait(timeout=0.5)
            release_profile.set()
        else:
            writer_thread.start()
            assert writer_history_read.wait(timeout=10), (
                "jurisdiction writer did not read empty history; "
                f"service_started={writer_service_started.is_set()}, "
                f"done={writer_done.is_set()}, results={results!r}, "
                f"errors={thread_errors!r}, "
                f"response={getattr(results.get('jurisdiction'), 'text', None)!r}"
            )
            guarded_thread.start()
            assert profile_first_sql_attempted.wait(timeout=10), (
                "guarded request did not begin its first database operation"
            )
            if profile_lock_attempted.is_set():
                assert not profile_read.is_set(), (
                    "guarded route read jurisdiction before acquiring the shared lock"
                )
                release_profile.set()
                guarded_finished_before_activation = profile_done.wait(timeout=0.5)
            else:
                assert profile_read.wait(timeout=10), (
                    "unlocked guarded route did not reach its jurisdiction read"
                )
                release_profile.set()
                guarded_finished_before_activation = profile_done.wait(timeout=5)
            release_writer.set()

        guarded_thread.join(timeout=20)
        writer_thread.join(timeout=20)
        assert not guarded_thread.is_alive(), "guarded route thread timed out"
        assert not writer_thread.is_alive(), "jurisdiction writer thread timed out"
        assert thread_errors == {}, f"request threads failed: {thread_errors!r}"
        assert set(results) == {"guarded", "jurisdiction"}
        assert results["jurisdiction"].status_code == 201, results["jurisdiction"].text
        assert first_sql_by_role["guarded"].upper().startswith(
            "UPDATE COMPANY_PAYROLL_JURISDICTIONS"
        ), first_sql_by_role
        assert first_sql_by_role["jurisdiction"].upper().startswith(
            "UPDATE COMPANY_PAYROLL_JURISDICTIONS"
        ), first_sql_by_role

        if winner == "guarded":
            assert not writer_finished_before_guard, (
                "initial jurisdiction activation committed while a guarded "
                "request still held the empty-history decision"
            )
            assert results["guarded"].status_code in {200, 201, 303}, results["guarded"].text
            assert commit_order.index("guarded") < commit_order.index("jurisdiction"), commit_order
        else:
            assert not guarded_finished_before_activation, (
                "guarded request completed after reading empty history while "
                "jurisdiction activation was still uncommitted"
            )
            assert results["guarded"].status_code == 422, results["guarded"].text
            assert "jurisdiction" in commit_order
            assert "guarded" not in commit_order

        with SessionFactory() as verify:
            configured = verify.query(PayrollJurisdiction).one()
            assert configured.country_code == "CA"
            if winner == "jurisdiction":
                if kind == "admin-create":
                    assert verify.query(Employee).count() == 1  # seeded row only
                    assert verify.query(OnboardingTask).count() == 0
                elif kind in {"admin-update", "portal-cookie", "portal-token"}:
                    stored = verify.query(Employee).filter_by(id=employee_id).one()
                    assert stored.filing_status == FilingStatus.SINGLE
                    assert stored.pay_rate == 25
                    assert stored.state is None
                    if kind in {"portal-cookie", "portal-token"}:
                        assert stored.portal_token_last_used is None
                        assert verify.query(PortalAccess).count() == 0
                elif kind == "pay-run":
                    assert verify.query(PayRun).count() == 0
                    assert verify.query(PayStub).count() == 0
            else:
                if kind == "admin-create":
                    stored = verify.query(Employee).filter(Employee.id != employee_id).one()
                    assert stored.filing_status == FilingStatus.SINGLE
                    assert verify.query(OnboardingTask).count() > 0
                elif kind == "admin-update":
                    stored = verify.query(Employee).filter_by(id=employee_id).one()
                    assert stored.filing_status == FilingStatus.MARRIED
                    assert stored.pay_rate == 99
                elif kind in {"portal-cookie", "portal-token"}:
                    stored = verify.query(Employee).filter_by(id=employee_id).one()
                    assert stored.filing_status == FilingStatus.MARRIED
                    assert stored.state == "CA"
                elif kind == "pay-run":
                    run = verify.query(PayRun).one()
                    assert run.jurisdiction_snapshot is None
                    assert verify.query(PayStub).count() == 1
    finally:
        release_profile.set()
        release_writer.set()
        if guarded_thread.ident is not None:
            guarded_thread.join(timeout=15)
        if writer_thread.ident is not None:
            writer_thread.join(timeout=15)
        event.remove(SessionClass, "after_begin", _tag_connection)
        event.remove(engine, "before_cursor_execute", _observe_lock_attempt)
        event.remove(SessionClass, "after_commit", _record_commit)
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()


@pytest.mark.parametrize(
    "kind",
    [
        "admin-create",
        "admin-update",
        "portal-cookie",
        "portal-token",
        "pay-run",
        "jurisdiction-writer",
    ],
)
def test_jurisdiction_lock_failure_fails_closed_before_mutation(
    client, tmp_path, kind
):
    """A real DB lock-acquisition error must stop each protected route."""
    import sqlite3

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import HTTPConnection

    from app.database import Base, get_db, enable_sqlite_tuning
    from app.main import app
    from app.models.hr import OnboardingTask
    from app.models.payroll import Employee, FilingStatus, PayRun, PayStub
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.models.portal_access import PortalAccess

    engine = create_engine(
        f"sqlite:///{(tmp_path / f'lock-failure-{kind}.sqlite').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )
    enable_sqlite_tuning(engine)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    token = "lock-failure-portal-token"
    with SessionFactory() as seed:
        employee = Employee(
            first_name="Failure",
            last_name="Closed",
            pay_type="hourly",
            pay_rate=25,
            filing_status=FilingStatus.SINGLE,
            work_state="WA",
            portal_token=token,
        )
        seed.add(employee)
        seed.commit()
        employee_id = employee.id

    def independent_db(request: HTTPConnection = None):  # type: ignore[assignment]
        session = SessionFactory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = independent_db

    @event.listens_for(engine, "before_cursor_execute")
    def fail_guard_lock(_connection, _cursor, statement, parameters, _context, _many):
        if "UPDATE COMPANY_PAYROLL_JURISDICTIONS" in statement.upper():
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("database is locked")
            )

    try:
        with TestClient(app, raise_server_exceptions=False) as request_client:
            request_client.cookies.update(client.cookies)
            if kind == "jurisdiction-writer":
                response = request_client.post(
                    "/api/settings/payroll-jurisdiction",
                    json=_jurisdiction_payload(),
                )
                assert response.status_code == 409, response.text
                assert response.headers.get("Retry-After") == "1"
            else:
                response = _guarded_request(request_client, kind, employee_id, token)
                assert response.status_code == 503, response.text

        with SessionFactory() as verify:
            assert verify.query(PayrollJurisdiction).count() == 0
            if kind == "admin-create":
                assert verify.query(Employee).count() == 1
                assert verify.query(OnboardingTask).count() == 0
            elif kind in {"admin-update", "portal-cookie", "portal-token"}:
                persisted = verify.query(Employee).filter_by(id=employee_id).one()
                assert persisted.filing_status == FilingStatus.SINGLE
                assert persisted.pay_rate == 25
                assert persisted.state is None
                assert verify.query(PortalAccess).count() == 0
            elif kind == "pay-run":
                assert verify.query(PayRun).count() == 0
                assert verify.query(PayStub).count() == 0
    finally:
        event.remove(engine, "before_cursor_execute", fail_guard_lock)
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()
