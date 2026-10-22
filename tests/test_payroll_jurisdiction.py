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


def test_date_max_is_rejected_and_get_remains_available(client):
    response = client.post(
        "/api/settings/payroll-jurisdiction",
        json=_payload("AB", date.max),
    )

    assert response.status_code == 422, response.text
    state = client.get("/api/settings/payroll-jurisdiction")
    assert state.status_code == 200, state.text
    assert state.json()["history"] == []


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


def test_post_commit_lock_does_not_break_jurisdiction_response_serialization(
    client, tmp_path
):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session as OrmSession, sessionmaker

    from app.database import get_db
    from app.main import app
    from app.models.payroll_jurisdiction import PayrollJurisdiction

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'post-commit-lock-jurisdiction.db').as_posix()}",
        connect_args={"timeout": 0},
    )
    PayrollJurisdiction.__table__.create(engine)

    class JurisdictionSession(OrmSession):
        pass

    Session = sessionmaker(
        bind=engine,
        class_=JurisdictionSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=True,
    )
    lock = engine.connect()
    lock_acquired = []

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def lock_database_after_commit(session):
        if session.get_bind() is engine:
            lock.exec_driver_sql("BEGIN EXCLUSIVE")
            lock_acquired.append(True)

    event.listen(JurisdictionSession, "after_commit", lock_database_after_commit)
    app.dependency_overrides[get_db] = file_backed_db
    request_client = TestClient(app, raise_server_exceptions=False)
    request_client.cookies.update(client.cookies)
    today = date.today()
    try:
        response = request_client.post(
            "/api/settings/payroll-jurisdiction",
            json=_payload("AB", today),
        )
    finally:
        lock.rollback()
        lock.close()
        event.remove(
            JurisdictionSession, "after_commit", lock_database_after_commit
        )
        request_client.close()

    assert lock_acquired == [True]
    assert response.status_code == 201, response.text
    assert response.json() == {
        "country_code": "CA",
        "province_code": "AB",
        "regulatory_scope": "provincially_regulated",
        "effective_from": today.isoformat(),
        "effective_to": None,
    }
    with Session() as persisted_session:
        persisted = persisted_session.query(PayrollJurisdiction).one()
        assert persisted.country_code == "CA"
        assert persisted.province_code == "AB"
        assert persisted.regulatory_scope == "provincially_regulated"
        assert persisted.effective_from == today
        assert persisted.effective_to is None
    engine.dispose()


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


def test_get_derives_active_jurisdiction_from_its_history_snapshot(monkeypatch):
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.routes.payroll_jurisdiction import _state
    from app.services import payroll_jurisdiction_service

    today = date.today()
    as_of = today + timedelta(days=35)
    change_date = today + timedelta(days=30)
    before_change = [
        PayrollJurisdiction(
            country_code="CA",
            province_code="AB",
            regulatory_scope="provincially_regulated",
            effective_from=today,
            effective_to=None,
        )
    ]
    after_change = [
        PayrollJurisdiction(
            country_code="CA",
            province_code="AB",
            regulatory_scope="provincially_regulated",
            effective_from=today,
            effective_to=change_date - timedelta(days=1),
        ),
        PayrollJurisdiction(
            country_code="CA",
            province_code="ON",
            regulatory_scope="provincially_regulated",
            effective_from=change_date,
            effective_to=None,
        ),
    ]
    query_count = 0

    def load_history(_db, *, lock=False):
        nonlocal query_count
        query_count += 1
        return before_change if query_count == 1 else after_change

    monkeypatch.setattr(
        payroll_jurisdiction_service, "_ordered_history", load_history
    )

    state = _state(object(), as_of)

    active_from_history = [
        item
        for item in state["history"]
        if item["effective_from"] <= as_of.isoformat()
        and (item["effective_to"] is None or as_of.isoformat() <= item["effective_to"])
    ]
    assert len(active_from_history) == 1
    assert state["province_code"] == active_from_history[0]["province_code"]
    assert state["effective_from"] == active_from_history[0]["effective_from"]
    assert state["effective_to"] == active_from_history[0]["effective_to"]
    assert query_count == 1


@pytest.mark.parametrize(
    "violation",
    ["effective_from", "open_range"],
)
def test_expected_timeline_uniqueness_violations_map_to_conflict(
    db_session, monkeypatch, violation
):
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.services.payroll_jurisdiction_service import (
        PayrollJurisdictionConflict,
        add_company_payroll_jurisdiction,
    )

    today = date.today()
    existing = PayrollJurisdiction(
        country_code="CA",
        province_code="AB",
        regulatory_scope="provincially_regulated",
        effective_from=today,
        effective_to=None,
    )
    db_session.add(existing)
    db_session.commit()

    commit = db_session.commit

    def commit_with_timeline_conflict():
        pending = next(item for item in db_session.new if isinstance(item, PayrollJurisdiction))
        if violation == "effective_from":
            pending.effective_from = today
        else:
            existing.effective_to = None
        commit()

    monkeypatch.setattr(db_session, "commit", commit_with_timeline_conflict)

    with pytest.raises(PayrollJurisdictionConflict, match="effective date"):
        add_company_payroll_jurisdiction(
            db_session,
            country_code="CA",
            province_code="ON",
            effective_from=today + timedelta(days=30),
            regulatory_scope="provincially_regulated",
        )


def test_unrelated_check_constraint_integrity_error_is_not_mislabeled(
    db_session, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.services.payroll_jurisdiction_service import (
        add_company_payroll_jurisdiction,
    )

    commit = db_session.commit

    def commit_with_invalid_scope():
        pending = next(item for item in db_session.new if isinstance(item, PayrollJurisdiction))
        pending.regulatory_scope = "federally_regulated"
        commit()

    monkeypatch.setattr(db_session, "commit", commit_with_invalid_scope)

    with pytest.raises(IntegrityError, match="ck_company_payroll_jurisdiction_scope"):
        add_company_payroll_jurisdiction(
            db_session,
            country_code="CA",
            province_code="ON",
            effective_from=date.today(),
            regulatory_scope="provincially_regulated",
        )
    assert db_session.query(PayrollJurisdiction).count() == 0


def test_simultaneous_initial_posts_preserve_one_consistent_timeline(
    client, monkeypatch, tmp_path
):
    from threading import Barrier, Lock, Thread

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import get_db
    from app.main import app
    from app.models.payroll_jurisdiction import PayrollJurisdiction
    from app.services import payroll_jurisdiction_service

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrent-jurisdiction.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )
    PayrollJurisdiction.__table__.create(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def file_backed_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = file_backed_db
    initial_reads = Barrier(2)
    result_lock = Lock()
    responses = []
    worker_errors = []
    initial_history_reads = 0
    original_ordered_history = payroll_jurisdiction_service._ordered_history

    def ordered_history_after_both_initial_reads(db, *, lock=False):
        nonlocal initial_history_reads
        history = original_ordered_history(db, lock=lock)
        if lock:
            with result_lock:
                initial_history_reads += 1
            initial_reads.wait(timeout=10)
        return history

    monkeypatch.setattr(
        payroll_jurisdiction_service,
        "_ordered_history",
        ordered_history_after_both_initial_reads,
    )

    def post_initial_jurisdiction(province):
        request_client = None
        try:
            request_client = TestClient(app, raise_server_exceptions=False)
            request_client.cookies.update(client.cookies)
            response = request_client.post(
                "/api/settings/payroll-jurisdiction",
                json=_payload(province, date.today()),
            )
            with result_lock:
                responses.append(response)
        except BaseException as exc:
            with result_lock:
                worker_errors.append(exc)
        finally:
            if request_client is not None:
                request_client.close()

    threads = [
        Thread(target=post_initial_jurisdiction, args=(province,), daemon=True)
        for province in ("AB", "ON")
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads), "POST worker timed out"
        assert initial_history_reads == 2
        assert worker_errors == []
        assert len(responses) == 2
        assert sorted(response.status_code for response in responses) == [201, 409]

        created = next(
            response for response in responses if response.status_code == 201
        )
        conflict = next(
            response for response in responses if response.status_code == 409
        )
        assert conflict.json()["detail"] in {
            "A payroll jurisdiction range already exists for that effective date.",
            "Payroll jurisdiction database is busy; retry the request.",
        }

        with Session() as persisted_session:
            records = persisted_session.query(PayrollJurisdiction).all()
            assert len(records) == 1
            stored = records[0]
            stored_snapshot = {
                "country_code": stored.country_code,
                "province_code": stored.province_code,
                "regulatory_scope": stored.regulatory_scope,
                "effective_from": stored.effective_from.isoformat(),
                "effective_to": stored.effective_to.isoformat()
                if stored.effective_to
                else None,
            }
            assert stored_snapshot == created.json()
            assert stored.effective_to is None

        history_client = TestClient(app, raise_server_exceptions=False)
        history_client.cookies.update(client.cookies)
        try:
            history_response = history_client.get("/api/settings/payroll-jurisdiction")
        finally:
            history_client.close()
        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert history["history"] == [stored_snapshot]
        assert history["province_code"] == stored_snapshot["province_code"]
        assert history["effective_from"] == stored_snapshot["effective_from"]
        assert history["effective_to"] is None
    finally:
        initial_reads.abort()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=15)
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()
