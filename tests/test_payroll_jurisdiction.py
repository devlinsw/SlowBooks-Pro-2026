"""Company-level Canadian payroll-jurisdiction history and resolution."""

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest


def _payload(province, effective_from, **extra):
    return {
        "country_code": "CA",
        "province_code": province,
        "effective_from": effective_from.isoformat(),
        "regulatory_scope": "provincially_regulated",
        **extra,
    }


def test_jurisdiction_is_unconfigured_until_a_company_sets_it(client):
    today = date.today().isoformat()
    response = client.get("/api/settings/payroll-jurisdiction")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "country_code": None,
        "province_code": None,
        "effective_from": None,
        "effective_to": None,
        "regulatory_scope": "provincially_regulated",
        "minimum_effective_from": today,
        "history": [],
    }


def test_get_returns_server_minimum_after_setup_and_scheduled_change(client):
    today = date.today()
    state = client.get("/api/settings/payroll-jurisdiction").json()
    assert state["minimum_effective_from"] == today.isoformat()

    initial = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload("AB", today)
    )
    assert initial.status_code == 201, initial.text
    state = client.get("/api/settings/payroll-jurisdiction").json()
    assert state["minimum_effective_from"] == (today + timedelta(days=1)).isoformat()

    scheduled = today + timedelta(days=30)
    changed = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload("ON", scheduled)
    )
    assert changed.status_code == 201, changed.text
    state = client.get("/api/settings/payroll-jurisdiction").json()
    assert (
        state["minimum_effective_from"] == (scheduled + timedelta(days=1)).isoformat()
    )


def test_jurisdiction_change_is_prospective_and_resolves_by_effective_date(client):
    today = date.today()
    change_date = today + timedelta(days=30)
    first = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload("AB", today)
    )
    assert first.status_code == 201, first.text

    changed = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload("ON", change_date),
    )
    assert changed.status_code == 201, changed.text

    current = client.get(
        "/api/settings/payroll-jurisdiction",
        params={"as_of": (change_date - timedelta(days=1)).isoformat()},
    )
    future = client.get(
        "/api/settings/payroll-jurisdiction",
        params={"as_of": change_date.isoformat()},
    )
    history = client.get("/api/settings/payroll-jurisdiction").json()["history"]

    assert current.json()["province_code"] == "AB"
    assert current.json()["effective_to"] == (change_date - timedelta(days=1)).isoformat()
    assert future.json()["province_code"] == "ON"
    assert future.json()["effective_from"] == change_date.isoformat()
    assert [item["province_code"] for item in history] == ["AB", "ON"]
    assert [item["effective_from"] for item in history] == [
        today.isoformat(),
        change_date.isoformat(),
    ]


@pytest.mark.parametrize("province", ["AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK"])
def test_each_supported_province_can_be_configured(client, province):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload(province, date.today()),
    )

    assert response.status_code == 201, response.text
    assert response.json()["country_code"] == "CA"
    assert response.json()["province_code"] == province


def test_database_rejects_two_open_jurisdiction_ranges(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.payroll_jurisdiction import PayrollJurisdiction

    today = date.today()
    db_session.add_all(
        [
            PayrollJurisdiction(
                country_code="CA",
                province_code="AB",
                regulatory_scope="provincially_regulated",
                effective_from=today,
            ),
            PayrollJurisdiction(
                country_code="CA",
                province_code="ON",
                regulatory_scope="provincially_regulated",
                effective_from=today + timedelta(days=1),
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_schedule_cannot_backdate_or_overlap_an_already_scheduled_change(client):
    today = date.today()
    scheduled = today + timedelta(days=30)
    initial = client.post(
        "/api/settings/payroll-jurisdiction", json=_payload("AB", today)
    )
    assert initial.status_code == 201, initial.text
    future = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload("ON", scheduled),
    )
    assert future.status_code == 201, future.text

    backdated = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload("MB", today - timedelta(days=1)),
    )
    overlapping = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload("NS", today + timedelta(days=15)),
    )

    assert backdated.status_code == 422, backdated.text
    assert "prospective" in backdated.json()["detail"].lower()
    assert overlapping.status_code == 409, overlapping.text
    assert "later than the latest scheduled" in overlapping.json()["detail"].lower()
    assert len(client.get("/api/settings/payroll-jurisdiction").json()["history"]) == 2


@pytest.mark.parametrize(
    "country, province",
    [
        ("US", "AB"),
        ("ca", "AB"),
        ("CAN", "AB"),
        ("CA", "QC"),
        ("CA", "YT"),
        ("CA", "NT"),
        ("CA", "NU"),
        ("CA", "ab"),
        ("CA", "A1"),
        ("CA", "AB1"),
    ],
)
def test_only_supported_uppercase_canadian_provinces_are_accepted(
    client, country, province
):
    r = client.post(
        "/api/settings/payroll-jurisdiction",
        json={
            "country_code": country,
            "province_code": province,
            "effective_from": date.today().isoformat(),
            "regulatory_scope": "provincially_regulated",
        },
    )

    assert r.status_code == 422, r.text
    assert client.get("/api/settings/payroll-jurisdiction").json()["history"] == []


def test_federally_regulated_payroll_is_explicitly_unsupported(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload(
            "ON", date.today(), regulatory_scope="federally_regulated"
        ),
    )

    assert response.status_code == 422, response.text
    assert "federal payroll is not supported" in response.text.lower()
    assert client.get("/api/settings/payroll-jurisdiction").json()["history"] == []


def test_api_requires_explicit_workplace_regulation_classification(client):
    payload = _payload("ON", date.today())
    payload.pop("regulatory_scope")

    response = client.post("/api/settings/payroll-jurisdiction", json=payload)

    assert response.status_code == 422, response.text
    assert "regulatory_scope" in response.text
    assert client.get("/api/settings/payroll-jurisdiction").json()["history"] == []


def test_malformed_effective_dates_are_refused_without_changing_history(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json={
            "country_code": "CA",
            "province_code": "AB",
            "effective_from": "2026-02-30",
            "regulatory_scope": "provincially_regulated",
        },
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/settings/payroll-jurisdiction").json()["history"] == []


def test_settings_ui_exposes_provincial_jurisdiction_and_explains_federal_limit():
    from pathlib import Path

    settings_js = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "settings.js"
    ).read_text(encoding="utf-8")

    assert "Payroll Jurisdiction" in settings_js
    assert "Federal payroll is not supported" in settings_js
    assert "payroll-jurisdiction" in settings_js
    for province in ("AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK"):
        assert province in settings_js


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_settings_ui_uses_server_minimum_and_requires_supported_scope():
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        ["node", str(root / "tests" / "js" / "payroll_jurisdiction_probe.js")],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    state = json.loads(out.stdout)

    assert state["minimum"] == state["value"] == "2031-02-03"
    assert state["federal_posts"] == 0
    assert "Federal payroll is not supported" in state["federal_status"]
    assert state["missing_scope_posts"] == 0
    assert (
        "Choose the workplace regulation classification"
        in state["missing_scope_status"]
    )
    assert state["provincial_posts"] == 1
    assert state["posted_scope"] == "provincially_regulated"
    assert state["minimum_is_rendered_as_min_and_value"] is True
    assert state["markup_has_required_scope"] is True
    assert state["markup_names_federal_unsupported"] is True


def test_locked_file_backed_sqlite_returns_retryable_conflict_not_500(client, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import get_db
    from app.main import app
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'locked-jurisdiction.db').as_posix()}",
        connect_args={"timeout": 0},
    )
    PayrollJurisdiction.__table__.create(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = file_backed_db
    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)
    lock = engine.connect()
    try:
        lock.exec_driver_sql("BEGIN EXCLUSIVE")
        response = request_client.post(
            "/api/settings/payroll-jurisdiction",
            json=_payload("AB", date.today()),
        )
    finally:
        lock.rollback()
        lock.close()
        request_client.close()
        engine.dispose()

    assert response.status_code == 409, response.text
    assert response.headers.get("retry-after") == "1"
    assert "database is busy" in response.json()["detail"].lower()


def test_unrelated_sqlite_operational_error_is_not_converted_to_lock_conflict(
    client, tmp_path
):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'missing-jurisdiction-table.db').as_posix()}",
        connect_args={"timeout": 0},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = file_backed_db
    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)
    try:
        response = request_client.post(
            "/api/settings/payroll-jurisdiction",
            json=_payload("AB", date.today()),
        )
    finally:
        request_client.close()
        engine.dispose()

    assert response.status_code == 500, response.text
