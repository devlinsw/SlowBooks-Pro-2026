"""Canadian employers must not enter legacy US-shaped employee tax data."""

from datetime import date, timedelta
from html.parser import HTMLParser

import pytest


class _PortalMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.profile_form_count = 0
        self.alert_count = 0
        self.input_names = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and "portal-form" in (attrs.get("class") or "").split():
            self.profile_form_count += 1
        if attrs.get("role") == "alert":
            self.alert_count += 1
        if tag in {"input", "select"} and attrs.get("name"):
            self.input_names.append(attrs["name"])


def _portal_markup(html):
    parser = _PortalMarkup()
    parser.feed(html)
    return parser


def _employee(client, **extra):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "Riley",
            "last_name": "Morgan",
            "pay_type": "hourly",
            "pay_rate": 28,
            "filing_status": "single",
            "work_state": "WA",
            "ssn_last_four": "1234",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _configure_canada(client, effective_from=None):
    return client.post(
        "/api/settings/payroll-jurisdiction",
        json={
            "country_code": "CA",
            "effective_from": (effective_from or date.today()).isoformat(),
        },
    )


def _w4_submission():
    return {
        "filing_status": "married",
        "multiple_jobs": True,
        "dependents_amount": 1500,
        "other_income_annual": 5000,
        "deductions_annual": 2000,
        "extra_withholding": 75,
        "work_state": "CA",
        "state_allowances": 2,
        "ssn_last_four": "9876",
    }


def _make_ambiguous_history(db_session):
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    today = date.today()
    db_session.add_all(
        [
            PayrollJurisdiction(
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today - timedelta(days=2),
                effective_to=today + timedelta(days=2),
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code="BC",
                regulatory_scope="provincially_regulated",
                effective_from=today,
                effective_to=None,
            ),
        ]
    )
    db_session.commit()


def test_no_history_keeps_legacy_admin_create_and_update(client):
    employee = _employee(client)

    response = client.put(
        f"/api/employees/{employee['id']}", json={"filing_status": "married"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["filing_status"] == "married"


def test_future_only_jurisdiction_keeps_legacy_admin_profile_behavior(client):
    configured = _configure_canada(client, date.today() + timedelta(days=5))
    assert configured.status_code == 201, configured.text

    employee = _employee(client)
    updated = client.put(
        f"/api/employees/{employee['id']}", json={"filing_status": "married"}
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["filing_status"] == "married"


def test_active_canada_blocks_employee_creation_before_any_profile_is_saved(
    client, db_session
):
    from app.models.hr import OnboardingTask
    from app.models.payroll import Employee

    configured = _configure_canada(client)
    assert configured.status_code == 201, configured.text
    before = db_session.query(Employee).count()
    tasks_before = db_session.query(OnboardingTask).count()

    response = client.post(
        "/api/employees",
        json={
            "first_name": "Riley",
            "last_name": "Morgan",
            **_w4_submission(),
        },
    )

    assert response.status_code == 422, response.text
    assert "Canadian employee setup is unavailable" in response.json()["detail"]
    assert db_session.query(Employee).count() == before
    assert db_session.query(OnboardingTask).count() == tasks_before


def test_active_canada_blocks_employee_update_without_mutating_profile(client, db_session):
    from app.models.payroll import Employee

    employee_data = _employee(client)
    employee = db_session.query(Employee).filter_by(id=employee_data["id"]).one()
    before = {
        "filing_status": employee.filing_status,
        "multiple_jobs": employee.multiple_jobs,
        "dependents_amount": employee.dependents_amount,
        "other_income_annual": employee.other_income_annual,
        "deductions_annual": employee.deductions_annual,
        "extra_withholding": employee.extra_withholding,
        "work_state": employee.work_state,
        "state_allowances": employee.state_allowances,
        "ssn_last_four": employee.ssn_last_four,
        "pay_rate": employee.pay_rate,
    }
    configured = _configure_canada(client)
    assert configured.status_code == 201, configured.text

    response = client.put(
        f"/api/employees/{employee.id}",
        json={**_w4_submission(), "pay_rate": 99},
    )

    assert response.status_code == 422, response.text
    assert "Canadian employee setup is unavailable" in response.json()["detail"]
    db_session.refresh(employee)
    assert {
        "filing_status": employee.filing_status,
        "multiple_jobs": employee.multiple_jobs,
        "dependents_amount": employee.dependents_amount,
        "other_income_annual": employee.other_income_annual,
        "deductions_annual": employee.deductions_annual,
        "extra_withholding": employee.extra_withholding,
        "work_state": employee.work_state,
        "state_allowances": employee.state_allowances,
        "ssn_last_four": employee.ssn_last_four,
        "pay_rate": employee.pay_rate,
    } == before


@pytest.mark.parametrize("legacy_token_path", [False, True])
def test_active_canada_hides_portal_us_profile_and_rejects_profile_saves(
    client, db_session, legacy_token_path
):
    from app.models.payroll import Employee

    employee_data = _employee(client)
    employee = db_session.query(Employee).filter_by(id=employee_data["id"]).one()
    original = {
        "filing_status": employee.filing_status,
        "multiple_jobs": employee.multiple_jobs,
        "dependents_amount": employee.dependents_amount,
        "other_income_annual": employee.other_income_annual,
        "deductions_annual": employee.deductions_annual,
        "extra_withholding": employee.extra_withholding,
        "address1": employee.address1,
        "state": employee.state,
    }
    configured = _configure_canada(client)
    assert configured.status_code == 201, configured.text
    token = client.get(f"/api/employees/{employee.id}/portal-token").json()[
        "portal_token"
    ]

    if legacy_token_path:
        page = client.get(f"/portal/{token}/profile")
    else:
        client.get(f"/portal/{token}")
        page = client.get("/portal/profile")
    assert page.status_code == 200, page.text
    assert 'role="alert"' in page.text
    assert "Canadian employee setup is unavailable" in page.text
    assert "Do not enter US W-4, state, or Social Security data" in page.text
    assert 'name="filing_status"' not in page.text
    assert "Form W-4 Election" not in page.text
    markup = _portal_markup(page.text)
    assert markup.alert_count == 1
    assert markup.profile_form_count == 0
    assert "filing_status" not in markup.input_names

    if legacy_token_path:
        save = client.post(
            f"/portal/{token}/profile",
            data={"filing_status": "married", "state": "CA", "address1": "New"},
        )
    else:
        save = client.post(
            "/portal/profile",
            data={"filing_status": "married", "state": "CA", "address1": "New"},
        )
    assert save.status_code == 422, save.text
    assert "Canadian employee setup is unavailable" in save.json()["detail"]
    db_session.refresh(employee)
    assert {
        "filing_status": employee.filing_status,
        "multiple_jobs": employee.multiple_jobs,
        "dependents_amount": employee.dependents_amount,
        "other_income_annual": employee.other_income_annual,
        "deductions_annual": employee.deductions_annual,
        "extra_withholding": employee.extra_withholding,
        "address1": employee.address1,
        "state": employee.state,
    } == original


def test_ambiguous_history_blocks_admin_api_and_portal_without_mutation(
    client, db_session
):
    from app.models.payroll import Employee

    employee_data = _employee(client)
    employee = db_session.query(Employee).filter_by(id=employee_data["id"]).one()
    original_filing_status = employee.filing_status
    _make_ambiguous_history(db_session)

    admin = client.put(
        f"/api/employees/{employee.id}", json={"filing_status": "married"}
    )
    assert admin.status_code == 409, admin.text
    assert "ambiguous" in admin.json()["detail"].lower()

    token = client.get(f"/api/employees/{employee.id}/portal-token").json()[
        "portal_token"
    ]
    client.get(f"/portal/{token}")
    page = client.get("/portal/profile")
    assert page.status_code == 200, page.text
    assert 'role="alert"' in page.text
    assert "payroll jurisdiction could not be confirmed" in page.text.lower()
    assert 'name="filing_status"' not in page.text

    portal = client.post(
        "/portal/profile",
        data={"filing_status": "married", "dependents_amount": "10"},
    )
    assert portal.status_code == 409, portal.text
    db_session.refresh(employee)
    assert employee.filing_status == original_filing_status
    assert employee.dependents_amount == 0


def test_jurisdiction_lookup_error_fails_closed_for_admin_and_portal(
    client, db_session, monkeypatch
):
    from app.models.payroll import Employee
    import app.routes.employees as employee_routes
    import app.routes.portal as portal_routes

    employee_data = _employee(client)
    employee = db_session.query(Employee).filter_by(id=employee_data["id"]).one()

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(
        employee_routes,
        "resolve_company_payroll_jurisdiction",
        unavailable,
        raising=False,
    )
    monkeypatch.setattr(
        portal_routes,
        "resolve_company_payroll_jurisdiction",
        unavailable,
        raising=False,
    )

    admin = client.put(
        f"/api/employees/{employee.id}", json={"filing_status": "married"}
    )
    assert admin.status_code == 503, admin.text
    assert "jurisdiction status is unavailable" in admin.json()["detail"].lower()

    token = client.get(f"/api/employees/{employee.id}/portal-token").json()[
        "portal_token"
    ]
    client.get(f"/portal/{token}")
    page = client.get("/portal/profile")
    assert page.status_code == 200, page.text
    assert 'role="alert"' in page.text
    assert 'name="filing_status"' not in page.text
    portal = client.post(
        "/portal/profile",
        data={"filing_status": "married", "address1": "New"},
    )
    assert portal.status_code == 503, portal.text
    db_session.refresh(employee)
    assert employee.filing_status.value == "single"
    assert employee.address1 is None


def test_no_history_portal_profile_remains_available(client):
    employee = _employee(client)
    token = client.get(f"/api/employees/{employee['id']}/portal-token").json()[
        "portal_token"
    ]
    client.get(f"/portal/{token}")

    page = client.get("/portal/profile")

    assert page.status_code == 200, page.text
    assert 'name="filing_status"' in page.text
    assert "Form W-4 Election" in page.text
    assert "Canadian employee setup is unavailable" not in page.text
    markup = _portal_markup(page.text)
    assert markup.alert_count == 0
    assert markup.profile_form_count == 1
    assert "filing_status" in markup.input_names


def test_future_only_jurisdiction_keeps_portal_profile_available(client, db_session):
    from app.models.payroll import Employee

    configured = _configure_canada(client, date.today() + timedelta(days=5))
    assert configured.status_code == 201, configured.text
    employee_data = _employee(client)
    employee = db_session.query(Employee).filter_by(id=employee_data["id"]).one()
    token = client.get(f"/api/employees/{employee.id}/portal-token").json()[
        "portal_token"
    ]
    client.get(f"/portal/{token}")

    page = client.get("/portal/profile")
    assert page.status_code == 200, page.text
    markup = _portal_markup(page.text)
    assert markup.profile_form_count == 1
    assert "filing_status" in markup.input_names

    saved = client.post(
        "/portal/profile",
        data={"filing_status": "married", "address1": "Kept"},
    )
    assert saved.status_code == 200, saved.text
    db_session.refresh(employee)
    assert employee.filing_status.value == "married"
    assert employee.address1 == "Kept"
