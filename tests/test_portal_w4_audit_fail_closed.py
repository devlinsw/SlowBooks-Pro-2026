"""W-4 submissions must fail closed when their access audit cannot commit."""

from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session as SessionClass


@pytest.mark.parametrize("auth_mode", ["cookie", "token"])
def test_w4_profile_is_not_saved_when_success_audit_commit_fails(
    client, db_session, auth_mode
):
    from app.models.payroll import Employee, FilingStatus
    from app.models.portal_access import PortalAccess

    employee = Employee(
        first_name="Audit",
        last_name="Failure",
        pay_type="hourly",
        pay_rate=25,
        filing_status=FilingStatus.SINGLE,
        multiple_jobs=False,
        dependents_amount=Decimal("125"),
        other_income_annual=Decimal("250"),
        deductions_annual=Decimal("375"),
        extra_withholding=Decimal("5"),
        address1="Old address",
        address2="Unit 2",
        city="Oldtown",
        state="WA",
        zip="98000",
        is_active=True,
    )
    db_session.add(employee)
    db_session.commit()

    token_response = client.get(f"/api/employees/{employee.id}/portal-token")
    assert token_response.status_code == 200, token_response.text
    token = token_response.json()["portal_token"]
    if auth_mode == "cookie":
        client.cookies.set("slowbooks_portal", token, path="/portal")
        path = "/portal/profile"
    else:
        path = f"/portal/{token}/profile"

    profile_fields = (
        "filing_status",
        "multiple_jobs",
        "dependents_amount",
        "other_income_annual",
        "deductions_annual",
        "extra_withholding",
        "address1",
        "address2",
        "city",
        "state",
        "zip",
    )
    original_profile = {field: getattr(employee, field) for field in profile_fields}
    failure_marker = "private database failure detail"

    def fail_portal_access_commit(session):
        if any(
            isinstance(row, PortalAccess)
            and row.employee_id == employee.id
            and row.success
            for row in session.new
        ):
            raise RuntimeError(failure_marker)

    event.listen(SessionClass, "before_commit", fail_portal_access_commit)
    try:
        response = client.post(
            path,
            data={
                "filing_status": "married",
                "multiple_jobs": "true",
                "dependents_amount": "2000",
                "other_income_annual": "800",
                "deductions_annual": "600",
                "extra_withholding": "25",
                "address1": "New address",
                "address2": "Suite 9",
                "city": "Newtown",
                "state": "CA",
                "zip": "90210",
            },
            follow_redirects=False,
        )
    finally:
        event.remove(SessionClass, "before_commit", fail_portal_access_commit)

    db_session.expire_all()
    stored_employee = db_session.query(Employee).filter_by(id=employee.id).one()
    stored_profile = {field: getattr(stored_employee, field) for field in profile_fields}
    assert stored_profile == original_profile
    assert response.status_code == 503
    assert failure_marker not in response.text
    assert db_session.query(PortalAccess).filter_by(employee_id=employee.id).count() == 0
