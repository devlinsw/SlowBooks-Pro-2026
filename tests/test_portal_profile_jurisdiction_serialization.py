"""Real-session regressions for portal profile jurisdiction read locks."""

from datetime import date
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as SessionClass
from sqlalchemy.orm import sessionmaker


_TOKEN = "portal-jurisdiction-race-token"


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_portal_profile_get_lock_failure_fails_closed(
    client, db_session, monkeypatch, fail_at
):
    from app.models.portal_access import PortalAccess
    from app.routes import portal as portal_routes

    employee = client.post(
        "/api/employees",
        json={
            "first_name": "Portal",
            "last_name": "Profile",
            "pay_type": "hourly",
            "pay_rate": 25,
            "filing_status": "single",
            "work_state": "WA",
            "ssn_last_four": "1234",
        },
    )
    assert employee.status_code == 201, employee.text
    token = client.get(
        f"/api/employees/{employee.json()['id']}/portal-token"
    ).json()["portal_token"]
    client.cookies.set("slowbooks_portal", token, path="/portal")
    original_lock = portal_routes.lock_company_payroll_jurisdiction
    lock_calls = 0

    def failed_lock(db):
        nonlocal lock_calls
        lock_calls += 1
        if lock_calls == fail_at:
            raise RuntimeError("lock unavailable")
        return original_lock(db)

    monkeypatch.setattr(portal_routes, "lock_company_payroll_jurisdiction", failed_lock)
    if fail_at == 3:
        def failed_lookup(*_args, **_kwargs):
            raise RuntimeError("jurisdiction lookup unavailable")

        monkeypatch.setattr(
            portal_routes, "resolve_company_payroll_jurisdiction", failed_lookup
        )
    response = client.get("/portal/profile")

    assert response.status_code == 503, response.text
    assert "US profile is blocked" in response.json()["detail"]
    assert lock_calls == fail_at
    assert db_session.query(PortalAccess).count() == (1 if fail_at >= 2 else 0)


@pytest.mark.parametrize("winner", ["activation", "profile"])
def test_portal_profile_get_and_canadian_activation_serialize(
    tmp_path, monkeypatch, winner
):
    from starlette.requests import HTTPConnection

    from app.database import Base, enable_sqlite_tuning, get_db
    from app.main import app
    from app.models.payroll import Employee, FilingStatus
    from app.services.payroll_jurisdiction_service import (
        add_company_payroll_jurisdiction,
    )
    from app.routes import portal as portal_routes

    database_path = tmp_path / f"portal-jurisdiction-{winner}.sqlite"
    assert not database_path.exists()
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    enable_sqlite_tuning(engine)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionFactory() as seed:
        seed.add(
            Employee(
                first_name="Portal",
                last_name="Race",
                pay_type="hourly",
                pay_rate=25,
                filing_status=FilingStatus.SINGLE,
                work_state="WA",
                portal_token=_TOKEN,
            )
        )
        seed.commit()

    def independent_db(request: HTTPConnection = None):  # type: ignore[assignment]
        session = SessionFactory()
        session.info["race_role"] = (
            "profile"
            if request is not None and request.url.path == "/portal/profile"
            else None
        )
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = independent_db
    profile_lock_attempted = Event()
    second_profile_lock_attempted = Event()
    activation_lock_attempted = Event()
    activation_before_commit = Event()
    release_activation = Event()
    profile_render_entered = Event()
    release_profile_render = Event()
    profile_done = Event()
    activation_done = Event()
    profile_lock_returned = Event()
    profile_employee_read = Event()
    results = {}
    errors = {}
    profile_lock_count = 0
    profile_sql_order = []

    def tag_connection(session, _transaction, connection):
        connection.info["race_role"] = session.info.get("race_role")

    def observe_sql(connection, _cursor, statement, _parameters, _context, _many):
        nonlocal profile_lock_count
        role = connection.info.get("race_role")
        upper = statement.upper()
        is_company_lock = "UPDATE COMPANY_PAYROLL_JURISDICTIONS" in upper
        if role == "profile":
            if is_company_lock:
                profile_lock_count += 1
                profile_sql_order.append("jurisdiction_lock")
                profile_lock_attempted.set()
                if profile_lock_count >= 2:
                    second_profile_lock_attempted.set()
            elif upper.lstrip().startswith("SELECT") and "FROM EMPLOYEES" in upper:
                profile_sql_order.append("employee_read")
                profile_employee_read.set()
            elif upper.lstrip().startswith("SELECT") and "FROM COMPANY_PAYROLL_JURISDICTIONS" in upper:
                profile_sql_order.append("jurisdiction_read")
        elif role == "activation" and is_company_lock:
            activation_lock_attempted.set()

    def pause_activation_commit(session):
        if (
            winner == "activation"
            and session.info.get("race_role") == "activation"
        ):
            activation_before_commit.set()
            if not release_activation.wait(timeout=15):
                raise TimeoutError("activation commit was not released")

    event.listen(SessionClass, "after_begin", tag_connection)
    event.listen(engine, "before_cursor_execute", observe_sql)
    event.listen(SessionClass, "before_commit", pause_activation_commit)
    original_profile_lock = portal_routes.lock_company_payroll_jurisdiction

    def observe_profile_lock_return(db):
        result = original_profile_lock(db)
        if db.info.get("race_role") == "profile":
            profile_lock_returned.set()
        return result

    monkeypatch.setattr(
        portal_routes,
        "lock_company_payroll_jurisdiction",
        observe_profile_lock_return,
    )
    original_render = portal_routes._render

    def pause_profile_render(name, db, **context):
        if name == "profile.html" and winner == "profile":
            profile_render_entered.set()
            if not release_profile_render.wait(timeout=15):
                raise TimeoutError("profile response construction was not released")
        return original_render(name, db, **context)

    monkeypatch.setattr(portal_routes, "_render", pause_profile_render)

    def get_profile():
        request_client = TestClient(app, raise_server_exceptions=False)
        request_client.cookies.set("slowbooks_portal", _TOKEN, path="/portal")
        try:
            results["profile"] = request_client.get("/portal/profile")
        except BaseException as exc:
            errors["profile"] = exc
        finally:
            request_client.close()
            profile_done.set()

    def activate_canada():
        try:
            with SessionFactory() as session:
                session.info["race_role"] = "activation"
                results["activation"] = add_company_payroll_jurisdiction(
                    session, country_code="CA", effective_from=date.today()
                )
        except BaseException as exc:
            errors["activation"] = exc
        finally:
            activation_done.set()

    profile_thread = Thread(target=get_profile, daemon=True)
    activation_thread = Thread(target=activate_canada, daemon=True)
    activation_finished_while_profile_held = False
    try:
        if winner == "activation":
            activation_thread.start()
            assert activation_before_commit.wait(timeout=10), (
                "activation did not reach its locked pre-commit state"
            )
            assert activation_lock_attempted.is_set(), (
                "activation did not acquire the shared lock before the profile GET started"
            )
            profile_thread.start()
            assert profile_lock_attempted.wait(timeout=10), (
                "profile GET did not acquire the jurisdiction lock before authentication reads"
            )
            assert not profile_lock_returned.wait(timeout=0.25), (
                "profile GET returned from the shared-lock call while activation "
                "still held its transaction"
            )
            assert not profile_employee_read.is_set(), (
                "profile GET read the employee while activation held the shared lock"
            )
            assert not profile_done.is_set(), (
                "profile GET completed while activation held the shared lock"
            )
            assert not activation_done.is_set(), (
                "activation released its transaction before the GET blocking check"
            )
            release_activation.set()
        else:
            profile_thread.start()
            assert profile_render_entered.wait(timeout=10), (
                "profile GET did not reach response construction"
            )
            assert second_profile_lock_attempted.is_set(), (
                "profile GET did not reacquire the jurisdiction lock after auth commits"
            )
            activation_thread.start()
            assert activation_lock_attempted.wait(timeout=10), (
                "activation did not attempt the jurisdiction lock"
            )
            activation_finished_while_profile_held = activation_done.wait(timeout=0.25)
            release_profile_render.set()

        assert profile_done.wait(timeout=15), "profile request timed out"
        assert activation_done.wait(timeout=15), "activation request timed out"
        assert errors == {}
        assert profile_lock_count == 2
        assert profile_sql_order.index("jurisdiction_lock") < profile_sql_order.index(
            "employee_read"
        )
        assert profile_sql_order.index("employee_read") < profile_sql_order.index(
            "jurisdiction_read"
        )

        page = results["profile"]
        assert page.status_code == 200, page.text
        if winner == "activation":
            assert "Canadian employee setup is unavailable" in page.text
            assert 'name="filing_status"' not in page.text
        else:
            assert activation_finished_while_profile_held is False
            assert 'name="filing_status"' in page.text
            assert "Canadian employee setup is unavailable" not in page.text
        assert results["activation"]["country_code"] == "CA"
    finally:
        release_activation.set()
        release_profile_render.set()
        for thread in (profile_thread, activation_thread):
            if thread.ident is not None:
                thread.join(timeout=15)
        event.remove(SessionClass, "after_begin", tag_connection)
        event.remove(engine, "before_cursor_execute", observe_sql)
        event.remove(SessionClass, "before_commit", pause_activation_commit)
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()
