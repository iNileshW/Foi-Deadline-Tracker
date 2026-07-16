"""UK GDPR retention: PII redaction after N days, and DSAR route.

The retention window redacts `requester` and `notes`. Case metadata
(ref, subject, dates, status, deadline, team) is retained because the
FOI statistical return has to survive the redaction.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import app as app_module
from retention import (
    DEFAULT_RETENTION_DAYS,
    REDACTED,
    find_due,
    purge_due,
    redact_request,
)
from schema import init_all
from users import User, create_user

CSRF = "test-csrf-token"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _seed_request(conn, *, ref, status, responded_days_ago=None, team="central"):
    responded_at = None
    if responded_days_ago is not None:
        responded_at = _iso(datetime.now(timezone.utc) - timedelta(days=responded_days_ago))
    conn.execute(
        "INSERT INTO requests "
        "(ref, requester, subject, received, deadline, status, notes, team, responded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ref, f"requester of {ref}", f"subject {ref}", "2026-01-01",
         "2026-02-01", status, "private note", team, responded_at),
    )
    conn.commit()


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "retention.db"
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    init_all(conn)
    yield conn
    conn.close()


# --- library-level ---


def test_find_due_returns_only_old_responded_rows(db):
    _seed_request(db, ref="OLD-1", status="Responded", responded_days_ago=1200)
    _seed_request(db, ref="OLD-2", status="Responded", responded_days_ago=1100)
    _seed_request(db, ref="RECENT", status="Responded", responded_days_ago=30)
    _seed_request(db, ref="OPEN", status="In progress")  # no responded_at
    due = find_due(db, days=DEFAULT_RETENTION_DAYS)
    refs = {r["ref"] for r in due}
    assert refs == {"OLD-1", "OLD-2"}


def test_find_due_ignores_already_redacted(db):
    _seed_request(db, ref="OLD", status="Responded", responded_days_ago=1200)
    ok = redact_request(db, 1, reason="test")
    assert ok
    assert find_due(db, days=DEFAULT_RETENTION_DAYS) == []


def test_redact_request_wipes_pii_only(db):
    _seed_request(db, ref="R-1", status="Responded", responded_days_ago=1200)
    redact_request(db, 1, reason="DSAR")
    row = db.execute("SELECT * FROM requests WHERE id = 1").fetchone()
    assert row["requester"] == REDACTED
    assert row["notes"] == REDACTED
    # Metadata retained.
    assert row["ref"] == "R-1"
    assert row["subject"] == "subject R-1"
    assert row["status"] == "Responded"
    assert row["received"] == "2026-01-01"
    assert row["deadline"] == "2026-02-01"
    assert row["team"] == "central"
    assert row["pii_redacted_at"] is not None


def test_redact_request_is_idempotent(db):
    _seed_request(db, ref="R", status="Responded", responded_days_ago=1200)
    assert redact_request(db, 1, reason="first") is True
    assert redact_request(db, 1, reason="second") is False


def test_redact_missing_row_returns_false(db):
    assert redact_request(db, 42, reason="ghost") is False


def test_redact_records_audit_event(db):
    _seed_request(db, ref="R", status="Responded", responded_days_ago=1200)
    actor = User(id=99, email="admin@x.gov.uk", role="admin", team="hq")
    redact_request(db, 1, actor=actor, reason="DSAR from requester")
    events = db.execute(
        "SELECT * FROM audit_events WHERE action = 'request.erase_pii'"
    ).fetchall()
    assert len(events) == 1
    e = events[0]
    assert e["actor_id"] == 99
    assert e["target_type"] == "request"
    assert e["target_id"] == 1
    before = json.loads(e["before_json"])
    after = json.loads(e["after_json"])
    assert before["requester"] != REDACTED
    assert after["requester"] == REDACTED
    assert after["_reason"] == "DSAR from requester"


def test_purge_due_redacts_everything_due(db):
    _seed_request(db, ref="OLD-1", status="Responded", responded_days_ago=1200)
    _seed_request(db, ref="OLD-2", status="Responded", responded_days_ago=1100)
    _seed_request(db, ref="RECENT", status="Responded", responded_days_ago=30)
    ids = purge_due(db, days=DEFAULT_RETENTION_DAYS)
    assert set(ids) == {1, 2}
    # Third row untouched.
    row = db.execute("SELECT requester FROM requests WHERE ref = 'RECENT'").fetchone()
    assert row["requester"] == "requester of RECENT"


def test_purge_due_dry_run_touches_nothing(db):
    _seed_request(db, ref="OLD", status="Responded", responded_days_ago=1200)
    ids = purge_due(db, days=DEFAULT_RETENTION_DAYS, dry_run=True)
    assert ids == []
    row = db.execute("SELECT requester, pii_redacted_at FROM requests WHERE id = 1").fetchone()
    assert row["requester"] != REDACTED
    assert row["pii_redacted_at"] is None


def test_configurable_window(db):
    _seed_request(db, ref="R", status="Responded", responded_days_ago=100)
    assert find_due(db, days=200) == []
    assert len(find_due(db, days=50)) == 1


# --- HTTP integration: DSAR route ---


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "dsar.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_all(conn)
    create_user(conn, "admin@x.gov.uk", "correct-horse-battery-pass", "admin", "hq")
    create_user(conn, "alice@x.gov.uk", "correct-horse-battery-pass", "caseworker", "central")
    _seed_request(conn, ref="R-1", status="Responded", responded_days_ago=10)
    conn.close()
    monkeypatch.setattr(app_module, "DB", str(db_path))
    with app_module.app.test_client() as c:
        yield c, db_path


def _login_as(c, uid):
    with c.session_transaction() as s:
        s["user_id"] = uid
        s["csrf_token"] = CSRF


def test_route_requires_admin(client):
    c, _ = client
    _login_as(c, uid=2)  # caseworker
    r = c.post("/request/1/erase-pii", data={"_csrf": CSRF, "reason": "test"})
    assert r.status_code == 403


def test_route_requires_login(client):
    c, _ = client
    # Prime a CSRF token so the CSRF guard is not the thing that fires.
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    r = c.post("/request/1/erase-pii", data={"_csrf": CSRF, "reason": "test"})
    # Anonymous with a valid CSRF → admin_required redirects to /login.
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_route_requires_csrf(client):
    c, _ = client
    _login_as(c, uid=1)
    r = c.post("/request/1/erase-pii", data={"reason": "test"})
    assert r.status_code == 400


def test_admin_can_erase(client):
    c, db_path = client
    _login_as(c, uid=1)
    r = c.post(
        "/request/1/erase-pii",
        data={"_csrf": CSRF, "reason": "DSAR from requester"},
    )
    assert r.status_code == 302

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT requester, notes, pii_redacted_at FROM requests WHERE id = 1"
    ).fetchone()
    events = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'request.erase_pii'"
    ).fetchone()[0]
    conn.close()
    assert row[0] == REDACTED
    assert row[1] == REDACTED
    assert row[2] is not None
    assert events == 1


def test_erase_returns_404_for_missing_request(client):
    c, _ = client
    _login_as(c, uid=1)
    r = c.post(
        "/request/999/erase-pii",
        data={"_csrf": CSRF, "reason": "test"},
    )
    assert r.status_code == 404


# --- responded_at auto-stamp on status transition ---


def test_status_transition_to_responded_stamps_responded_at(client):
    c, db_path = client
    _login_as(c, uid=1)  # admin — sees all teams
    # Seed one In-progress request in central team.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO requests (ref, requester, subject, received, deadline, status, team) "
        "VALUES ('IP', 'x', 'x', '2026-01-01', '2026-02-01', 'In progress', 'central')"
    )
    conn.commit()
    new_id = conn.execute("SELECT id FROM requests WHERE ref='IP'").fetchone()[0]
    conn.close()

    r = c.post(
        f"/request/{new_id}",
        data={"_csrf": CSRF, "status": "Responded", "notes": "done"},
    )
    assert r.status_code == 302

    conn = sqlite3.connect(db_path)
    responded_at = conn.execute(
        "SELECT responded_at FROM requests WHERE id = ?", (new_id,)
    ).fetchone()[0]
    conn.close()
    assert responded_at is not None
