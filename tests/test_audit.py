"""Audit-trail tests.

These are the tests the ICO auditor implicitly cares about: every
mutating action must leave a record that names the actor, the target,
and enough context to reconstruct what changed.
"""

import json
import sqlite3

import pytest

import app as app_module
from audit import init_audit_table, record_event
from users import create_user, init_users_table

CSRF = "test-csrf-token"
USER_EMAIL = "alice@example.gov.uk"
USER_PASSWORD = "correct-horse-battery-staple"
ADMIN_EMAIL = "admin@example.gov.uk"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT, requester TEXT, subject TEXT,
            received TEXT, deadline TEXT, status TEXT, notes TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO requests "
        "(ref, requester, subject, received, deadline, status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("FOI-T-1", "Alice E", "Bridges", "2026-04-02", "2026-05-05",
         "Received", ""),
    )
    init_users_table(conn)
    init_audit_table(conn)
    create_user(conn, USER_EMAIL, USER_PASSWORD, "caseworker", "central")
    create_user(conn, ADMIN_EMAIL, USER_PASSWORD, "admin", "central")
    conn.close()

    monkeypatch.setattr(app_module, "DB", str(db_path))
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c, db_path


def _login(c, csrf=CSRF, user_id=1):
    with c.session_transaction() as s:
        s["user_id"] = user_id
        s["csrf_token"] = csrf


def _fetch_events(db_path, action=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if action is None:
            return conn.execute(
                "SELECT * FROM audit_events ORDER BY id"
            ).fetchall()
        return conn.execute(
            "SELECT * FROM audit_events WHERE action = ? ORDER BY id",
            (action,),
        ).fetchall()
    finally:
        conn.close()


def test_login_success_is_audited(client):
    c, db_path = client
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    c.post(
        "/login",
        data={"_csrf": CSRF, "email": USER_EMAIL, "password": USER_PASSWORD},
    )
    events = _fetch_events(db_path, "login.success")
    assert len(events) == 1
    assert events[0]["actor_email"] == USER_EMAIL
    assert events[0]["actor_id"] == 1
    assert events[0]["ip"] is not None


def test_login_failure_is_audited_with_no_actor_id(client):
    c, db_path = client
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    c.post(
        "/login",
        data={"_csrf": CSRF, "email": "nobody@example.gov.uk", "password": "x"},
    )
    events = _fetch_events(db_path, "login.failure")
    assert len(events) == 1
    assert events[0]["actor_id"] is None
    # The attempted email is captured for brute-force visibility.
    assert events[0]["actor_email"] == "nobody@example.gov.uk"


def test_login_failure_never_stores_password(client):
    c, db_path = client
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    hostile_password = "sneaky-pw-that-must-not-leak"
    c.post(
        "/login",
        data={"_csrf": CSRF, "email": "nobody@x.gov.uk", "password": hostile_password},
    )
    conn = sqlite3.connect(db_path)
    for row in conn.execute("SELECT * FROM audit_events").fetchall():
        for value in row:
            assert value is None or hostile_password not in str(value)
    conn.close()


def test_logout_is_audited(client):
    c, db_path = client
    _login(c)
    c.post("/logout", data={"_csrf": CSRF})
    events = _fetch_events(db_path, "logout")
    assert len(events) == 1
    assert events[0]["actor_id"] == 1
    assert events[0]["actor_email"] == USER_EMAIL


def test_request_create_writes_after_snapshot(client):
    c, db_path = client
    _login(c)
    c.post(
        "/new",
        data={
            "_csrf": CSRF,
            "ref": "FOI-NEW-1",
            "requester": "New Requester",
            "subject": "New subject",
            "received": "2026-06-01",
        },
    )
    events = _fetch_events(db_path, "request.create")
    assert len(events) == 1
    e = events[0]
    assert e["actor_id"] == 1
    assert e["target_type"] == "request"
    assert e["before_json"] is None
    after = json.loads(e["after_json"])
    assert after["ref"] == "FOI-NEW-1"
    assert after["requester"] == "New Requester"
    assert after["status"] == "Received"


def test_request_update_captures_before_and_after(client):
    c, db_path = client
    _login(c)
    c.post(
        "/request/1",
        data={"_csrf": CSRF, "status": "In progress", "notes": "started"},
    )
    events = _fetch_events(db_path, "request.update")
    assert len(events) == 1
    before = json.loads(events[0]["before_json"])
    after = json.loads(events[0]["after_json"])
    assert before["status"] == "Received"
    assert before["notes"] == ""
    assert after["status"] == "In progress"
    assert after["notes"] == "started"


def test_audit_view_requires_admin(client):
    c, _ = client
    # Non-admin (caseworker Alice, id=1) → 403
    _login(c, user_id=1)
    r = c.get("/audit")
    assert r.status_code == 403


def test_audit_view_visible_to_admin(client):
    c, db_path = client
    # Seed one event so the page has content
    conn = sqlite3.connect(db_path)
    record_event(
        conn,
        "login.success",
        actor_id=2,
        actor_email=ADMIN_EMAIL,
        ip="127.0.0.1",
        user_agent="test-agent",
    )
    conn.close()
    _login(c, user_id=2)
    r = c.get("/audit")
    assert r.status_code == 200
    assert ADMIN_EMAIL.encode() in r.data


def test_audit_view_redirects_when_anonymous(client):
    c, _ = client
    r = c.get("/audit")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_audit_rows_are_indexed_by_target(client):
    """Query by target_type/target_id must be fast enough that we
    added an index. This test asserts the index exists rather than
    timing anything — a schema-level regression guard."""
    _, db_path = client
    conn = sqlite3.connect(db_path)
    idx = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='audit_events'"
    ).fetchall()
    conn.close()
    names = {r[0] for r in idx}
    assert "idx_audit_target" in names
    assert "idx_audit_actor" in names


def test_record_event_rejects_unknown_action(tmp_path):
    conn = sqlite3.connect(tmp_path / "a.db")
    init_audit_table(conn)
    with pytest.raises(ValueError, match="unknown audit action"):
        record_event(conn, "totally.made.up")


def test_user_agent_is_truncated(tmp_path):
    conn = sqlite3.connect(tmp_path / "a.db")
    init_audit_table(conn)
    huge = "x" * 2000
    record_event(conn, "login.success", user_agent=huge)
    row = conn.execute("SELECT user_agent FROM audit_events").fetchone()
    conn.close()
    assert len(row[0]) <= 255


def test_audit_filter_by_target(client):
    _, db_path = client
    conn = sqlite3.connect(db_path)
    record_event(conn, "request.create", target_type="request", target_id=1)
    record_event(conn, "request.create", target_type="request", target_id=2)
    from audit import list_events
    only_one = list_events(conn, target_type="request", target_id=1)
    conn.close()
    assert len(only_one) == 1
    assert only_one[0]["target_id"] == 1
