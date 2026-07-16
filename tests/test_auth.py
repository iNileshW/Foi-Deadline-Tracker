"""Tests for authentication, session handling, and CSRF.

Same throwaway-SQLite pattern as test_sql_injection.py, but here the
fixture seeds a real hashed user via `create_user()` so that /login
authenticates against production code paths.
"""

import sqlite3

import pytest

import app as app_module
from users import create_user, init_users_table

USER_EMAIL = "alice@example.gov.uk"
USER_PASSWORD = "correct-horse-battery-staple"
CSRF = "test-csrf-token"


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
    init_users_table(conn)
    create_user(conn, USER_EMAIL, USER_PASSWORD, "caseworker", "central")
    conn.close()

    monkeypatch.setattr(app_module, "DB", str(db_path))
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c, db_path


def _login_session(c, uid=1):
    with c.session_transaction() as s:
        s["user_id"] = uid
        s["csrf_token"] = CSRF


def test_index_redirects_when_not_logged_in(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_new_redirects_when_not_logged_in(client):
    c, _ = client
    r = c.get("/new")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_detail_redirects_when_not_logged_in(client):
    c, _ = client
    r = c.get("/request/1")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_login_wrong_password_returns_401(client):
    c, _ = client
    # Grab a CSRF token from the GET page.
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    r = c.post(
        "/login",
        data={"_csrf": CSRF, "email": USER_EMAIL, "password": "wrong"},
    )
    assert r.status_code == 401
    with c.session_transaction() as s:
        assert "user_id" not in s


def test_login_unknown_email_returns_401(client):
    c, _ = client
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    r = c.post(
        "/login",
        data={
            "_csrf": CSRF,
            "email": "nobody@example.gov.uk",
            "password": USER_PASSWORD,
        },
    )
    assert r.status_code == 401


def test_login_success_grants_access(client):
    c, _ = client
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    r = c.post(
        "/login",
        data={"_csrf": CSRF, "email": USER_EMAIL, "password": USER_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302
    # Session now authorises the protected route.
    r = c.get("/")
    assert r.status_code == 200


def test_logout_clears_session(client):
    c, _ = client
    _login_session(c)
    assert c.get("/").status_code == 200
    r = c.post("/logout", data={"_csrf": CSRF})
    assert r.status_code == 302
    r = c.get("/")
    assert r.status_code == 302  # redirected back to /login


def test_post_without_csrf_is_rejected(client):
    c, _ = client
    _login_session(c)
    r = c.post(
        "/new",
        data={
            "ref": "FOI-X",
            "requester": "X",
            "subject": "X",
            "received": "2026-06-01",
        },
    )
    assert r.status_code == 400


def test_post_with_wrong_csrf_is_rejected(client):
    c, _ = client
    _login_session(c)
    r = c.post(
        "/new",
        data={
            "_csrf": "not-the-right-token",
            "ref": "FOI-X",
            "requester": "X",
            "subject": "X",
            "received": "2026-06-01",
        },
    )
    assert r.status_code == 400


def test_password_not_stored_in_plaintext(client):
    _, db_path = client
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT password_hash FROM users WHERE email = ?", (USER_EMAIL,)
    ).fetchone()
    conn.close()
    assert row is not None
    stored = row[0]
    assert stored != USER_PASSWORD
    assert USER_PASSWORD not in stored
    assert stored.startswith(("pbkdf2:", "scrypt:", "argon2"))


def test_disabled_user_cannot_login(client):
    c, db_path = client
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE users SET disabled_at = ? WHERE email = ?",
        ("2026-07-15T00:00:00", USER_EMAIL),
    )
    conn.commit()
    conn.close()
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    r = c.post(
        "/login",
        data={"_csrf": CSRF, "email": USER_EMAIL, "password": USER_PASSWORD},
    )
    assert r.status_code == 401


def test_login_next_redirect_only_relative(client):
    """`?next=` must not permit off-site redirects."""
    c, _ = client
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    r = c.post(
        "/login?next=https://evil.example.com/steal",
        data={"_csrf": CSRF, "email": USER_EMAIL, "password": USER_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["Location"].startswith("/")


def test_password_min_length_enforced(tmp_path):
    conn = sqlite3.connect(tmp_path / "u.db")
    init_users_table(conn)
    with pytest.raises(ValueError, match="12 characters"):
        create_user(conn, "a@b.gov.uk", "short", "caseworker", "central")


def test_invalid_role_rejected(tmp_path):
    conn = sqlite3.connect(tmp_path / "u.db")
    init_users_table(conn)
    with pytest.raises(ValueError, match="invalid role"):
        create_user(conn, "a@b.gov.uk", USER_PASSWORD, "root", "central")


def test_session_id_rotated_on_login(client):
    """A pre-login session token must not remain valid after login."""
    c, _ = client
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
        s["pre_login_marker"] = "should-be-cleared"
    r = c.post(
        "/login",
        data={"_csrf": CSRF, "email": USER_EMAIL, "password": USER_PASSWORD},
    )
    assert r.status_code == 302
    with c.session_transaction() as s:
        assert "pre_login_marker" not in s
        assert "user_id" in s
