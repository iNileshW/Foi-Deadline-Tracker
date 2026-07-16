"""Team-based data separation.

Two directorates joining the tracker share the database but not each
other's requests. A caseworker on team A must not see, edit, or even
learn of a request owned by team B. An admin can see everything.
"""

import sqlite3

import pytest

import app as app_module
from audit import init_audit_table
from schema import init_requests_table
from users import create_user, init_users_table

CSRF = "test-csrf-token"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    init_requests_table(conn)
    init_users_table(conn)
    init_audit_table(conn)
    # Users: 1 = admin (any team), 2 = alice on 'central',
    # 3 = bob on 'rail', 4 = charlie on 'central'
    create_user(conn, "admin@x.gov.uk", "correct-horse-battery-pass", "admin", "hq")
    create_user(conn, "alice@x.gov.uk", "correct-horse-battery-pass", "caseworker", "central")
    create_user(conn, "bob@x.gov.uk", "correct-horse-battery-pass", "caseworker", "rail")
    create_user(conn, "charlie@x.gov.uk", "correct-horse-battery-pass", "caseworker", "central")
    # Requests: one per team + one legacy unassigned
    conn.execute(
        "INSERT INTO requests (ref, requester, subject, received, deadline, status, notes, team) "
        "VALUES ('C-1','C req','central subject','2026-04-01','2026-05-01','Received','','central')"
    )
    conn.execute(
        "INSERT INTO requests (ref, requester, subject, received, deadline, status, notes, team) "
        "VALUES ('R-1','R req','rail subject','2026-04-01','2026-05-01','Received','','rail')"
    )
    conn.execute(
        "INSERT INTO requests (ref, requester, subject, received, deadline, status, notes, team) "
        "VALUES ('L-1','L req','legacy subject','2026-04-01','2026-05-01','Received','','')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(app_module, "DB", str(db_path))
    with app_module.app.test_client() as c:
        yield c, db_path


def _login_as(c, user_id):
    with c.session_transaction() as s:
        s["user_id"] = user_id
        s["csrf_token"] = CSRF


# --- list view ---


def test_caseworker_sees_own_team_and_legacy_only(env):
    c, _ = env
    _login_as(c, user_id=2)  # alice, central
    r = c.get("/")
    body = r.data.decode()
    assert "central subject" in body
    assert "legacy subject" in body
    assert "rail subject" not in body


def test_caseworker_from_other_team_sees_different_scope(env):
    c, _ = env
    _login_as(c, user_id=3)  # bob, rail
    r = c.get("/")
    body = r.data.decode()
    assert "rail subject" in body
    assert "legacy subject" in body
    assert "central subject" not in body


def test_admin_sees_all_requests(env):
    c, _ = env
    _login_as(c, user_id=1)
    r = c.get("/")
    body = r.data.decode()
    assert "central subject" in body
    assert "rail subject" in body
    assert "legacy subject" in body


# --- detail view ---


def test_caseworker_cannot_view_other_team_request(env):
    c, _ = env
    _login_as(c, user_id=2)  # central
    # R-1 belongs to rail (id=2)
    r = c.get("/request/2")
    assert r.status_code == 404


def test_caseworker_can_view_own_team_request(env):
    c, _ = env
    _login_as(c, user_id=2)  # central
    r = c.get("/request/1")
    assert r.status_code == 200
    assert b"central subject" in r.data


def test_caseworker_can_view_legacy_unassigned_request(env):
    c, _ = env
    _login_as(c, user_id=2)  # central
    r = c.get("/request/3")
    assert r.status_code == 200
    assert b"legacy subject" in r.data


def test_admin_can_view_any_request(env):
    c, _ = env
    _login_as(c, user_id=1)
    for req_id in (1, 2, 3):
        assert c.get(f"/request/{req_id}").status_code == 200


# --- update prevention ---


def test_caseworker_cannot_update_other_team_request(env):
    c, db_path = env
    _login_as(c, user_id=2)  # central
    r = c.post(
        "/request/2",
        data={"_csrf": CSRF, "status": "Responded", "notes": "leaked"},
    )
    assert r.status_code == 404

    conn = sqlite3.connect(db_path)
    status = conn.execute(
        "SELECT status FROM requests WHERE id = 2"
    ).fetchone()[0]
    conn.close()
    # Unmodified.
    assert status == "Received"


# --- create stamps user's team ---


def test_new_request_inherits_users_team(env):
    c, db_path = env
    _login_as(c, user_id=2)  # alice, central
    r = c.post(
        "/new",
        data={
            "_csrf": CSRF,
            "ref": "C-2",
            "requester": "new",
            "subject": "new subject",
            "received": "2026-06-01",
        },
    )
    assert r.status_code == 302
    conn = sqlite3.connect(db_path)
    team = conn.execute(
        "SELECT team FROM requests WHERE ref = 'C-2'"
    ).fetchone()[0]
    conn.close()
    assert team == "central"


def test_new_request_created_by_other_team_invisible_to_first(env):
    c, _ = env
    _login_as(c, user_id=3)  # bob, rail
    c.post(
        "/new",
        data={
            "_csrf": CSRF,
            "ref": "R-2",
            "requester": "new",
            "subject": "rail-only new subject",
            "received": "2026-06-01",
        },
    )

    _login_as(c, user_id=2)  # alice, central
    r = c.get("/")
    assert b"rail-only new subject" not in r.data


# --- search respects scope ---


def test_search_stays_within_team_scope(env):
    c, _ = env
    _login_as(c, user_id=2)  # central
    r = c.get("/", query_string={"q": "rail"})
    body = r.data.decode()
    assert "rail subject" not in body


# --- migration ---


def test_alter_adds_team_column_on_legacy_db(tmp_path):
    """A DB created without the team column must gain it on init."""
    p = tmp_path / "legacy.db"
    conn = sqlite3.connect(p)
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
        "INSERT INTO requests (ref, requester, subject, received, deadline, status, notes) "
        "VALUES ('OLD-1','x','x','2026-01-01','2026-02-01','Received','')"
    )
    conn.commit()
    conn.close()

    # Idempotent init should add the column.
    from schema import init_requests_table
    conn = sqlite3.connect(p)
    init_requests_table(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(requests)")}
    assert "team" in cols
    # Pre-existing rows migrate to team='' (unassigned).
    team = conn.execute(
        "SELECT team FROM requests WHERE ref = 'OLD-1'"
    ).fetchone()[0]
    conn.close()
    assert team == ""
