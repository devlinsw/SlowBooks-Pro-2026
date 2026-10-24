"""Fail-closed jurisdiction boundary for the date-free overtime classifier."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest


def _classifier_spy(monkeypatch):
    from app.routes import time_entries

    original = time_entries.classify_period
    spy = Mock(wraps=original)
    monkeypatch.setattr(time_entries, "classify_period", spy)
    return time_entries, spy, original


def _classify(client):
    return client.post(
        "/api/time-entries/classify",
        json={"weeks": [[8, 8, 8, 8, 8]]},
    )


def _track_route_lock_and_rollback(monkeypatch):
    from app.routes import time_entries
    from app.services.payroll_jurisdiction_service import (
        lock_company_payroll_jurisdiction,
    )

    observed = {}

    def capture_route_session(db):
        lock_company_payroll_jurisdiction(db)
        observed["db"] = db
        original_rollback = db.rollback

        def record_rollback():
            observed.setdefault("rollback_transactions", []).append(
                db.get_transaction()
            )
            original_rollback()
            observed["transaction_after_rollback"] = db.get_transaction()

        db.rollback = record_rollback

    monkeypatch.setattr(
        time_entries,
        "lock_company_payroll_jurisdiction",
        capture_route_session,
        raising=False,
    )
    return observed


def _assert_route_rollback_completed(observed):
    assert observed["db"] is not None
    assert len(observed["rollback_transactions"]) == 1
    assert observed["rollback_transactions"][0] is not None
    assert observed["transaction_after_rollback"] is None
    assert observed["db"].get_transaction() is None


def _company_history(db_session, effective_from, effective_to=None):
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    record = PayrollJurisdiction(
        country_code="CA",
        province_code=None,
        regulatory_scope="provincially_regulated",
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db_session.add(record)
    db_session.commit()
    return record


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


def test_no_jurisdiction_history_preserves_classifier_result(client, monkeypatch):
    _, classifier_spy, original = _classifier_spy(monkeypatch)
    weeks = [[Decimal("8")] * 5]
    expected = original(weeks, "WA")

    response = _classify(client)

    assert response.status_code == 200, response.text
    assert response.json() == {key: float(value) for key, value in expected.items()}
    classifier_spy.assert_called_once_with(weeks, "WA")


def test_no_history_classifier_runs_before_jurisdiction_lock_transaction_ends(
    client, monkeypatch
):
    from app.routes import time_entries
    from app.services.payroll_jurisdiction_service import (
        lock_company_payroll_jurisdiction,
    )

    locked = {}
    original = time_entries.classify_period

    def record_lock(db):
        lock_company_payroll_jurisdiction(db)
        locked["db"] = db
        locked["transaction"] = db.get_transaction()

    def classify_while_locked(weeks, state):
        assert "transaction" in locked
        assert locked["db"].get_transaction() is locked["transaction"]
        assert (
            locked["db"].info.get("payroll_jurisdiction_guard_transaction")
            is locked["transaction"]
        )
        return original(weeks, state)

    classifier_spy = Mock(side_effect=classify_while_locked)
    monkeypatch.setattr(
        time_entries, "lock_company_payroll_jurisdiction", record_lock, raising=False
    )
    monkeypatch.setattr(time_entries, "classify_period", classifier_spy)

    response = _classify(client)

    assert response.status_code == 200, response.text
    classifier_spy.assert_called_once()


def test_future_only_company_history_blocks_date_free_classifier(
    client, db_session, monkeypatch
):
    _company_history(db_session, date.today() + timedelta(days=5))
    _, classifier_spy, _ = _classifier_spy(monkeypatch)

    response = _classify(client)

    assert response.status_code == 422, response.text
    classifier_spy.assert_not_called()


def test_active_company_history_blocks_date_free_classifier(
    client, db_session, monkeypatch
):
    _company_history(db_session, date.today())
    _, classifier_spy, _ = _classifier_spy(monkeypatch)

    response = _classify(client)

    assert response.status_code == 422, response.text
    classifier_spy.assert_not_called()


def test_employee_province_history_alone_blocks_date_free_classifier(
    client, db_session, monkeypatch
):
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction

    employee = _employee(client)
    db_session.add(
        EmployeePayrollJurisdiction(
            employee_id=employee["id"],
            country_code="CA",
            province_code="BC",
            regulatory_scope="provincially_regulated",
            effective_from=date.today(),
        )
    )
    db_session.commit()
    _, classifier_spy, _ = _classifier_spy(monkeypatch)

    response = _classify(client)

    assert response.status_code == 422, response.text
    classifier_spy.assert_not_called()


def test_future_only_employee_province_history_blocks_date_free_classifier(
    client, db_session, monkeypatch
):
    from app.models.employee_payroll_jurisdiction import EmployeePayrollJurisdiction
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    employee = _employee(client)
    assert db_session.query(PayrollJurisdiction).count() == 0
    db_session.add(
        EmployeePayrollJurisdiction(
            employee_id=employee["id"],
            country_code="CA",
            province_code="BC",
            regulatory_scope="provincially_regulated",
            effective_from=date.today() + timedelta(days=5),
        )
    )
    db_session.commit()
    _, classifier_spy, _ = _classifier_spy(monkeypatch)

    response = _classify(client)

    assert response.status_code == 422, response.text
    classifier_spy.assert_not_called()


def test_ambiguous_company_history_returns_conflict_before_classification(
    client, db_session, monkeypatch
):
    today = date.today()
    _company_history(db_session, today, today + timedelta(days=3))
    _company_history(db_session, today + timedelta(days=2))
    _, classifier_spy, _ = _classifier_spy(monkeypatch)

    response = _classify(client)

    assert response.status_code == 409, response.text
    assert "ambiguous" in response.json()["detail"].lower()
    classifier_spy.assert_not_called()


@pytest.mark.parametrize("failure", ["lock", "history"])
def test_expected_jurisdiction_failures_return_generic_503_without_classification(
    client, monkeypatch, failure
):
    from app.routes import time_entries
    from app.services.payroll_jurisdiction_service import (
        PayrollJurisdictionLockUnsupported,
    )
    from sqlalchemy.exc import SQLAlchemyError

    _, classifier_spy, _ = _classifier_spy(monkeypatch)
    if failure == "lock":

        def fail_lock(_db):
            raise PayrollJurisdictionLockUnsupported("secret lock details")

        monkeypatch.setattr(
            time_entries, "lock_company_payroll_jurisdiction", fail_lock, raising=False
        )
    else:

        def fail_history(_db):
            raise SQLAlchemyError("secret history details")

        monkeypatch.setattr(
            time_entries,
            "list_company_payroll_jurisdictions",
            fail_history,
            raising=False,
        )

    response = _classify(client)

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == (
        "Payroll jurisdiction status is unavailable; overtime classification is blocked."
    )
    assert "secret" not in response.text
    classifier_spy.assert_not_called()


def test_blocked_classifier_rejection_rolls_back_route_transaction(
    client, db_session, monkeypatch
):
    _company_history(db_session, date.today())
    _, classifier_spy, _ = _classifier_spy(monkeypatch)
    observed = _track_route_lock_and_rollback(monkeypatch)

    response = _classify(client)

    assert response.status_code == 422, response.text
    _assert_route_rollback_completed(observed)
    classifier_spy.assert_not_called()


def test_history_error_response_rolls_back_route_transaction(client, monkeypatch):
    from app.routes import time_entries
    from sqlalchemy.exc import SQLAlchemyError

    _, classifier_spy, _ = _classifier_spy(monkeypatch)
    observed = _track_route_lock_and_rollback(monkeypatch)

    def fail_history(_db):
        raise SQLAlchemyError("secret history details")

    monkeypatch.setattr(
        time_entries,
        "list_company_payroll_jurisdictions",
        fail_history,
        raising=False,
    )

    response = _classify(client)

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == (
        "Payroll jurisdiction status is unavailable; overtime classification is blocked."
    )
    _assert_route_rollback_completed(observed)
    classifier_spy.assert_not_called()


def test_unexpected_runtime_error_is_not_mislabeled_as_outage(client, monkeypatch):
    from app.routes import time_entries

    def programming_bug(_db):
        raise RuntimeError("unexpected programming bug")

    monkeypatch.setattr(
        time_entries, "lock_company_payroll_jurisdiction", programming_bug, raising=False
    )

    with pytest.raises(RuntimeError, match="unexpected programming bug"):
        _classify(client)
