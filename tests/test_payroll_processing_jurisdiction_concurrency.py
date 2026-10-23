"""Real separate-session race tests for payroll processing and activation."""

from datetime import date
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


@pytest.mark.parametrize("winner", ["activation", "processing"])
def test_us_pay_run_processing_and_canadian_activation_serialize(
    client, tmp_path, winner
):
    from app.database import Base, enable_sqlite_tuning, get_db
    from app.main import app
    from app.models.accounts import Account, AccountType
    from app.models.job_costing import JobCost
    from app.models.payroll import (
        Employee,
        FilingStatus,
        PayRun,
        PayRunStatus,
        PayStub,
    )
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.models.transactions import Transaction, TransactionLine
    from sqlalchemy.orm import Session as SessionClass
    from starlette.requests import HTTPConnection

    engine = create_engine(
        f"sqlite:///{(tmp_path / f'process-activation-{winner}.sqlite').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    enable_sqlite_tuning(engine)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    pay_date = date.today()
    with SessionFactory() as seed:
        employee = Employee(
            first_name="Race",
            last_name="Process",
            pay_type="hourly",
            pay_rate=25,
            filing_status=FilingStatus.SINGLE,
            work_state="WA",
            ssn_last_four="1234",
        )
        seed.add_all(
            [
                employee,
                Account(
                    name="Payroll Wages",
                    account_number="6110",
                    account_type=AccountType.EXPENSE,
                ),
                Account(
                    name="Checking",
                    account_number="1000",
                    account_type=AccountType.ASSET,
                ),
            ]
        )
        seed.flush()
        run = PayRun(period_start=pay_date, period_end=pay_date, pay_date=pay_date)
        seed.add(run)
        seed.flush()
        run_id = run.id
        seed.add(
            PayStub(
                pay_run_id=run_id,
                employee_id=employee.id,
                gross_pay=1000,
                net_pay=1000,
            )
        )
        seed.commit()

    def independent_db(request: HTTPConnection = None):  # type: ignore[assignment]
        session = SessionFactory()
        path = request.url.path if request is not None else ""
        session.info["race_role"] = (
            "activation"
            if path == "/api/settings/payroll-jurisdiction"
            else "processing"
            if path.endswith("/process")
            else None
        )
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = independent_db

    activation_before_commit = Event()
    processing_before_commit = Event()
    release_activation = Event()
    release_processing = Event()
    first_sql_event = {"activation": Event(), "processing": Event()}
    lock_attempted = {"activation": Event(), "processing": Event()}
    request_done = {"activation": Event(), "processing": Event()}
    results = {}
    errors = {}
    first_sql = {}
    commit_order = []

    @event.listens_for(SessionClass, "after_begin")
    def tag_connection(session, _transaction, connection):
        connection.info["race_role"] = session.info.get("race_role")

    @event.listens_for(engine, "before_cursor_execute")
    def observe_sql(connection, _cursor, statement, _parameters, _context, _many):
        role = connection.info.get("race_role")
        if role not in first_sql_event:
            return
        upper = statement.upper()
        if role not in first_sql:
            first_sql[role] = statement
            first_sql_event[role].set()
        if "UPDATE COMPANY_PAYROLL_JURISDICTIONS" in upper:
            lock_attempted[role].set()

    @event.listens_for(SessionClass, "before_commit")
    def pause_winner_commit(session):
        role = session.info.get("race_role")
        if winner == "activation" and role == "activation":
            activation_before_commit.set()
            if not release_activation.wait(timeout=15):
                raise TimeoutError("activation commit was not released")
        elif winner == "processing" and role == "processing":
            processing_before_commit.set()
            if not release_processing.wait(timeout=15):
                raise TimeoutError("processing commit was not released")

    @event.listens_for(SessionClass, "after_commit")
    def record_commit(session):
        role = session.info.get("race_role")
        if role in {"activation", "processing"}:
            commit_order.append(role)

    def request(kind):
        request_client = TestClient(app, raise_server_exceptions=False)
        try:
            request_client.cookies.update(client.cookies)
            if kind == "activation":
                results[kind] = request_client.post(
                    "/api/settings/payroll-jurisdiction",
                    json={
                        "country_code": "CA",
                        "province_code": "ON",
                        "regulatory_scope": "provincially_regulated",
                        "effective_from": pay_date.isoformat(),
                    },
                )
            else:
                results[kind] = request_client.post(
                    f"/api/payroll/{run_id}/process"
                )
        except BaseException as exc:
            errors[kind] = exc
        finally:
            request_client.close()
            request_done[kind].set()

    threads = {
        "activation": Thread(target=request, args=("activation",), daemon=True),
        "processing": Thread(target=request, args=("processing",), daemon=True),
    }
    processing_lock_waited = False
    processing_finished_early = False
    activation_lock_waited = False
    activation_finished_early = False
    try:
        if winner == "activation":
            threads["activation"].start()
            assert activation_before_commit.wait(timeout=10), (
                "activation did not reach its uncommitted timeline write"
            )
            threads["processing"].start()
            assert first_sql_event["processing"].wait(timeout=10), (
                "processing did not issue SQL"
            )
            processing_lock_waited = lock_attempted["processing"].wait(timeout=1)
            processing_finished_early = request_done["processing"].wait(timeout=0.25)
            release_activation.set()
        else:
            threads["processing"].start()
            assert processing_before_commit.wait(timeout=10), (
                "processing did not reach its uncommitted journal/status write"
            )
            threads["activation"].start()
            assert first_sql_event["activation"].wait(timeout=10), (
                "activation did not issue SQL"
            )
            activation_lock_waited = lock_attempted["activation"].wait(timeout=1)
            activation_finished_early = request_done["activation"].wait(timeout=0.25)
            release_processing.set()

        for thread in threads.values():
            thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads.values()), (
            "concurrent request timed out"
        )
        assert errors == {}, errors
        assert set(results) == {"activation", "processing"}
        for role in ("activation", "processing"):
            assert first_sql[role].upper().startswith(
                "UPDATE COMPANY_PAYROLL_JURISDICTIONS"
            ), first_sql

        if winner == "activation":
            assert processing_lock_waited
            assert not processing_finished_early
            assert results["activation"].status_code == 201, results["activation"].text
            assert results["processing"].status_code == 422, results["processing"].text
            assert commit_order == ["activation"], commit_order
        else:
            assert activation_lock_waited
            assert not activation_finished_early
            assert results["processing"].status_code == 200, results["processing"].text
            assert results["activation"].status_code == 409, results["activation"].text
            assert commit_order == ["processing"], commit_order

        with SessionFactory() as verify:
            stored_run = verify.get(PayRun, run_id)
            assert stored_run is not None
            timeline = verify.query(PayrollJurisdiction).all()
            transactions = verify.query(Transaction).all()
            lines = verify.query(TransactionLine).all()
            burden_rows = verify.query(JobCost).all()
            if winner == "activation":
                assert len(timeline) == 1
                assert results["activation"].json()["effective_from"] == pay_date.isoformat()
                assert stored_run.status is PayRunStatus.DRAFT
                assert stored_run.transaction_id is None
                assert stored_run.burden_job_cost_id is None
                assert transactions == []
                assert lines == []
                assert burden_rows == []
            else:
                assert timeline == []
                assert stored_run.status is PayRunStatus.PROCESSED
                assert stored_run.transaction_id is not None
                assert stored_run.burden_job_cost_id is None
                assert len(transactions) == 1
                assert {line.transaction_id for line in lines} == {
                    stored_run.transaction_id
                }
                assert len(lines) == 2
                assert burden_rows == []
    finally:
        release_activation.set()
        release_processing.set()
        for thread in threads.values():
            if thread.ident is not None:
                thread.join(timeout=15)
        event.remove(SessionClass, "after_begin", tag_connection)
        event.remove(engine, "before_cursor_execute", observe_sql)
        event.remove(SessionClass, "before_commit", pause_winner_commit)
        event.remove(SessionClass, "after_commit", record_commit)
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()
