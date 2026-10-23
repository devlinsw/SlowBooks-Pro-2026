"""Separate-session HTTP races for employee province assignment and activation."""

from datetime import date
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as SessionClass
from sqlalchemy.orm import sessionmaker


@pytest.mark.parametrize("winner", ["activation", "assignment"])
def test_employee_assignment_and_company_activation_serialize(
    client, tmp_path, monkeypatch, winner
):
    from starlette.requests import HTTPConnection

    from app.database import Base, enable_sqlite_tuning, get_db
    from app.main import app
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction
    from app.models.payroll import Employee, FilingStatus
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.services import payroll_jurisdiction_service as jurisdiction_service

    database_path = tmp_path / f"assignment-activation-{winner}.sqlite"
    assert not database_path.exists()
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    enable_sqlite_tuning(engine)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionFactory() as seed:
        employee = Employee(
            first_name="Race",
            last_name="Assignment",
            pay_type="hourly",
            pay_rate=25,
            filing_status=FilingStatus.SINGLE,
            work_state="WA",
        )
        seed.add(employee)
        seed.commit()
        employee_id = employee.id

    def independent_db(request: HTTPConnection = None):  # type: ignore[assignment]
        session = SessionFactory()
        path = request.url.path if request is not None else ""
        session.info["race_role"] = (
            "activation"
            if path == "/api/settings/payroll-jurisdiction"
            else "assignment"
            if path.endswith(f"/employees/{employee_id}")
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
    activation_lock_attempted = Event()
    assignment_lock_attempted = Event()
    activation_before_commit = Event()
    release_activation = Event()
    assignment_service_lock_acquired = Event()
    release_assignment = Event()
    activation_done = Event()
    assignment_done = Event()
    results = {}
    errors = {}

    def tag_connection(session, _transaction, connection):
        connection.info["race_role"] = session.info.get("race_role")

    def observe_sql(connection, _cursor, statement, _parameters, _context, _many):
        if "UPDATE COMPANY_PAYROLL_JURISDICTIONS" not in statement.upper():
            return
        role = connection.info.get("race_role")
        if role == "activation":
            activation_lock_attempted.set()
        elif role == "assignment":
            assignment_lock_attempted.set()

    def pause_activation_commit(session):
        if winner == "activation" and session.info.get("race_role") == "activation":
            activation_before_commit.set()
            if not release_activation.wait(timeout=15):
                raise TimeoutError("activation commit was not released")

    event.listen(SessionClass, "after_begin", tag_connection)
    event.listen(engine, "before_cursor_execute", observe_sql)
    event.listen(SessionClass, "before_commit", pause_activation_commit)
    original_lock = jurisdiction_service.lock_company_payroll_jurisdiction

    def pause_assignment_after_lock(session):
        result = original_lock(session)
        if (
            winner == "assignment"
            and session.info.get("race_role") == "assignment"
            and not assignment_service_lock_acquired.is_set()
        ):
            assignment_service_lock_acquired.set()
            if not release_assignment.wait(timeout=15):
                raise TimeoutError("assignment transaction was not released")
        return result

    monkeypatch.setattr(
        jurisdiction_service,
        "lock_company_payroll_jurisdiction",
        pause_assignment_after_lock,
    )

    def post(kind):
        request_client = TestClient(app, raise_server_exceptions=False)
        request_client.cookies.update(client.cookies)
        try:
            if kind == "activation":
                results[kind] = request_client.post(
                    "/api/settings/payroll-jurisdiction",
                    json={
                        "country_code": "CA",
                        "effective_from": date.today().isoformat(),
                    },
                )
            else:
                results[kind] = request_client.post(
                    f"/api/settings/payroll-jurisdiction/employees/{employee_id}",
                    json={
                        "country_code": "CA",
                        "province_code": "ON",
                        "regulatory_scope": "provincially_regulated",
                        "effective_from": date.today().isoformat(),
                    },
                )
        except BaseException as exc:
            errors[kind] = exc
        finally:
            request_client.close()
            (activation_done if kind == "activation" else assignment_done).set()

    activation_thread = Thread(target=post, args=("activation",), daemon=True)
    assignment_thread = Thread(target=post, args=("assignment",), daemon=True)
    activation_finished_while_assignment_held = False
    assignment_finished_while_activation_held = False
    try:
        if winner == "activation":
            activation_thread.start()
            assert activation_before_commit.wait(timeout=10), (
                "activation did not reach its locked pre-commit state"
            )
            assignment_thread.start()
            assert assignment_lock_attempted.wait(timeout=10), (
                "assignment did not attempt the jurisdiction lock"
            )
            assignment_finished_while_activation_held = assignment_done.wait(timeout=0.25)
            release_activation.set()
        else:
            assignment_thread.start()
            assert assignment_service_lock_acquired.wait(timeout=10), (
                "assignment did not hold the shared jurisdiction lock"
            )
            activation_thread.start()
            assert activation_lock_attempted.wait(timeout=10), (
                "activation did not attempt the jurisdiction lock"
            )
            activation_finished_while_assignment_held = activation_done.wait(timeout=0.25)
            release_assignment.set()

        assert activation_done.wait(timeout=15), "activation request timed out"
        assert assignment_done.wait(timeout=15), "assignment request timed out"
        assert errors == {}
        assert results["activation"].status_code == 201, results["activation"].text
        if winner == "activation":
            assert assignment_finished_while_activation_held is False
            assert results["assignment"].status_code == 201, results["assignment"].text
        else:
            assert activation_finished_while_assignment_held is False
            assert results["assignment"].status_code == 422, results["assignment"].text

        with SessionFactory() as persisted:
            assert persisted.query(PayrollJurisdiction).count() == 1
            assignments = (
                persisted.query(EmployeePayrollJurisdiction)
                .filter_by(employee_id=employee_id)
                .all()
            )
            if winner == "activation":
                assert len(assignments) == 1
                assert assignments[0].province_code == "ON"
                assert assignments[0].effective_from == date.today()
            else:
                assert assignments == []
    finally:
        release_activation.set()
        release_assignment.set()
        for thread in (activation_thread, assignment_thread):
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
