"""Container health probe.

/healthz opens the DB and pokes each schema-critical table. Anything
that stops the app from serving real requests should surface here
before the orchestrator sends live traffic.
"""

import sqlite3

import pytest

import app as app_module
from audit import init_audit_table
from users import init_users_table


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
    conn.close()
    monkeypatch.setattr(app_module, "DB", str(db_path))
    with app_module.app.test_client() as c:
        yield c, db_path


def test_healthz_returns_200_when_schema_present(client):
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_healthz_is_public(client):
    """No login required — orchestrator probes must not need auth."""
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200


def test_healthz_returns_503_when_db_unreachable(tmp_path, monkeypatch):
    """A DB path that cannot be opened at all should surface as
    unhealthy. Pointing at a directory forces sqlite to fail on
    connect."""
    monkeypatch.setattr(app_module, "DB", str(tmp_path))  # tmp_path is a dir
    with app_module.app.test_client() as c:
        r = c.get("/healthz")
    assert r.status_code == 503
    assert r.get_json() == {"status": "unhealthy"}
