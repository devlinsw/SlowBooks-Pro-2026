"""Company payroll-jurisdiction guard for the US gross-up calculator."""

from datetime import date, timedelta
from unittest.mock import Mock


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


def _jurisdiction(client, province, effective_from):
    return client.post(
        "/api/settings/payroll-jurisdiction",
        json={
            "country_code": "CA",
            "effective_from": effective_from.isoformat(),
        },
    )


def _gross_up(client, employee_id):
    return client.post(
        "/api/payroll/gross-up",
        json={
            "employee_id": employee_id,
            "target_net": 2000,
            "supplemental": True,
        },
    )


def test_active_canadian_jurisdiction_blocks_gross_up_before_us_tax_calculation(
    client, monkeypatch
):
    from app.routes.payroll import runs as payroll_runs

    employee = _employee(client)
    configured = _jurisdiction(client, "AB", date.today())
    assert configured.status_code == 201, configured.text

    ytd_spy = Mock(wraps=payroll_runs.employee_ytd)
    supplemental_ytd_spy = Mock(wraps=payroll_runs._ytd_supplemental)
    withholding_spy = Mock(wraps=payroll_runs.calculate_withholdings)
    monkeypatch.setattr(payroll_runs, "employee_ytd", ytd_spy)
    monkeypatch.setattr(payroll_runs, "_ytd_supplemental", supplemental_ytd_spy)
    monkeypatch.setattr(payroll_runs, "calculate_withholdings", withholding_spy)

    response = _gross_up(client, employee["id"])

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == (
        "Canadian gross-up calculation support is not enabled yet."
    )
    ytd_spy.assert_not_called()
    supplemental_ytd_spy.assert_not_called()
    withholding_spy.assert_not_called()


def test_future_only_jurisdiction_keeps_pre_effective_us_gross_up_behavior(client):
    employee = _employee(client)
    configured = _jurisdiction(client, "AB", date.today() + timedelta(days=5))
    assert configured.status_code == 201, configured.text

    response = _gross_up(client, employee["id"])

    assert response.status_code == 200, response.text
    assert response.json()["gross"] > response.json()["target_net"]
    assert abs(response.json()["net"] - response.json()["target_net"]) <= 1.0


def test_ambiguous_jurisdiction_history_rejects_gross_up(client, db_session):
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    employee = _employee(client)
    today = date.today()
    db_session.add_all(
        [
            PayrollJurisdiction(
                country_code="CA",
                province_code="AB",
                regulatory_scope="provincially_regulated",
                effective_from=today,
                effective_to=today + timedelta(days=2),
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today + timedelta(days=2),
                effective_to=None,
            ),
        ]
    )
    db_session.commit()

    response = _gross_up(client, employee["id"])

    assert response.status_code == 409, response.text
    assert "ambiguous" in response.json()["detail"].lower()
