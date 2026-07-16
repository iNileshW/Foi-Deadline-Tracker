"""Login rate limiter.

Threshold: 5 failed attempts in a 15-minute rolling window, keyed on
attempted email OR source IP. Sixth attempt returns 429 with
`Retry-After` and does not check the password.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import app as app_module
from audit import init_audit_table, record_event
from ratelimit import (
    MAX_FAILURES,
    WINDOW_MINUTES,
    failure_count,
    is_locked,
    seconds_until_unlock,
)
from users import create_user, init_users_table

CSRF = "test-csrf-token"
USER_EMAIL = "alice@example.gov.uk"
USER_PASSWORD = "correct-horse-battery-staple"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _seed_failures(conn, *, count, email=None, ip=None, when=None):
    when = when or datetime.now(timezone.utc)
    for i in range(count):
        conn.execute(
            "INSERT INTO audit_events (occurred_at, action, actor_email, ip) "
            "VALUES (?, 'login.failure', ?, ?)",
            (_iso(when - timedelta(seconds=i)), email, ip),
        )
    conn.commit()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "rl.db"
    conn = sqlite3.connect(path)
    init_audit_table(conn)
    yield conn
    conn.close()


# --- pure library tests ---


def test_no_failures_not_locked(db):
    assert failure_count(db, email="a@x.gov.uk", ip="1.2.3.4") == 0
    assert not is_locked(db, email="a@x.gov.uk", ip="1.2.3.4")


def test_counts_failures_within_window(db):
    _seed_failures(db, count=3, email="a@x.gov.uk", ip="1.2.3.4")
    assert failure_count(db, email="a@x.gov.uk", ip=None) == 3
    assert failure_count(db, email=None, ip="1.2.3.4") == 3


def test_email_or_ip_match(db):
    """A row matching email OR ip must count."""
    _seed_failures(db, count=2, email="a@x.gov.uk", ip="1.1.1.1")
    _seed_failures(db, count=2, email="b@y.gov.uk", ip="2.2.2.2")
    # Query by email a AND ip 2.2.2.2 → OR match → both sets count.
    assert failure_count(db, email="a@x.gov.uk", ip="2.2.2.2") == 4


def test_lock_at_threshold(db):
    _seed_failures(db, count=MAX_FAILURES - 1, email="a@x.gov.uk")
    assert not is_locked(db, email="a@x.gov.uk", ip=None)
    _seed_failures(db, count=1, email="a@x.gov.uk")
    assert is_locked(db, email="a@x.gov.uk", ip=None)


def test_window_expiry_releases_lock(db):
    old = datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES + 5)
    _seed_failures(db, count=MAX_FAILURES, email="a@x.gov.uk", when=old)
    assert not is_locked(db, email="a@x.gov.uk", ip=None)


def test_seconds_until_unlock_positive_when_locked(db):
    now = datetime.now(timezone.utc)
    _seed_failures(db, count=MAX_FAILURES, email="a@x.gov.uk", when=now)
    s = seconds_until_unlock(db, email="a@x.gov.uk", ip=None, now=now)
    # Should be roughly WINDOW_MINUTES * 60 seconds.
    assert 60 * (WINDOW_MINUTES - 1) < s <= 60 * WINDOW_MINUTES + 1


def test_seconds_until_unlock_zero_when_no_failures(db):
    assert seconds_until_unlock(db, email="a@x.gov.uk", ip=None) == 0


def test_no_key_returns_zero(db):
    assert failure_count(db, email=None, ip=None) == 0
    assert not is_locked(db, email=None, ip=None)


# --- HTTP integration tests ---


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
    init_audit_table(conn)
    create_user(conn, USER_EMAIL, USER_PASSWORD, "caseworker", "central")
    conn.close()
    monkeypatch.setattr(app_module, "DB", str(db_path))
    with app_module.app.test_client() as c:
        yield c, db_path


def _login(c, email=USER_EMAIL, password="wrong"):
    c.get("/login")
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    return c.post(
        "/login",
        data={"_csrf": CSRF, "email": email, "password": password},
    )


def test_five_failures_then_429(client):
    c, _ = client
    for _ in range(MAX_FAILURES):
        r = _login(c, password="wrong")
        assert r.status_code == 401
    # Sixth attempt: 429 regardless of password correctness.
    r = _login(c, password="wrong")
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) > 0


def test_correct_password_rejected_during_lockout(client):
    """Even the real password is refused while the user is locked out."""
    c, _ = client
    for _ in range(MAX_FAILURES):
        _login(c, password="wrong")
    r = _login(c, password=USER_PASSWORD)
    assert r.status_code == 429
    with c.session_transaction() as s:
        assert "user_id" not in s


def test_blocked_attempt_is_audited(client):
    c, db_path = client
    for _ in range(MAX_FAILURES):
        _login(c, password="wrong")
    _login(c, password="wrong")
    conn = sqlite3.connect(db_path)
    blocked = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'login.blocked'"
    ).fetchone()[0]
    conn.close()
    assert blocked == 1


def test_ip_throttle_spans_emails(client):
    """A single IP can't sidestep the limit by rotating attempted emails."""
    c, _ = client
    for i in range(MAX_FAILURES):
        _login(c, email=f"user{i}@x.gov.uk", password="wrong")
    r = _login(c, email="userN@x.gov.uk", password="wrong")
    assert r.status_code == 429


def test_unknown_email_still_returns_401_before_lockout(client):
    c, _ = client
    r = _login(c, email="nobody@x.gov.uk", password="whatever12345")
    assert r.status_code == 401
