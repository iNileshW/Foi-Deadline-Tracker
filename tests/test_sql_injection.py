"""Regression tests: user input must not be interpretable as SQL.

Each test drives the Flask app end-to-end against a throwaway SQLite
database. Payloads are the classic hostile strings that would have
worked against the inherited f-string queries in app.py.
"""

import sqlite3

import pytest

import app as app_module
from users import init_users_table

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
    conn.execute(
        "INSERT INTO requests "
        "(ref, requester, subject, received, deadline, status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "FOI-TEST-1",
            "Alice Example",
            "Bridge inspections",
            "2026-04-02",
            "2026-05-05",
            "Received",
            "",
        ),
    )
    init_users_table(conn)
    conn.commit()
    conn.close()

    monkeypatch.setattr(app_module, "DB", str(db_path))
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        # Simulate a logged-in session for the routes under test.
        with c.session_transaction() as s:
            s["user_id"] = 1
            s["csrf_token"] = CSRF
        yield c, db_path


def _row_count(db_path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    finally:
        conn.close()


def test_search_drop_table_neutralised(client):
    c, db_path = client
    r = c.get("/", query_string={"q": "'; DROP TABLE requests; --"})
    assert r.status_code == 200
    assert _row_count(db_path) == 1


def test_search_union_leak_neutralised(client):
    c, _ = client
    payload = "%' UNION SELECT sql,sql,sql,sql,sql,sql,sql,sql FROM sqlite_master --"
    r = c.get("/", query_string={"q": payload})
    assert r.status_code == 200
    assert b"CREATE TABLE" not in r.data
    assert b"Alice Example" not in r.data


def test_search_literal_apostrophe_is_safe(client):
    c, _ = client
    r = c.get("/", query_string={"q": "O'Brien"})
    assert r.status_code == 200


def test_new_request_persists_apostrophes(client):
    c, db_path = client
    r = c.post(
        "/new",
        data={
            "_csrf": CSRF,
            "ref": "FOI-TEST-2",
            "requester": "O'Brien",
            "subject": "Roads with 'apostrophes' and ; semicolons",
            "received": "2026-06-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM requests WHERE ref = ?", ("FOI-TEST-2",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["requester"] == "O'Brien"
    assert row["subject"] == "Roads with 'apostrophes' and ; semicolons"


def test_detail_update_preserves_hostile_notes(client):
    c, db_path = client
    hostile = "Note with 'quotes'; DROP TABLE requests; --"
    r = c.post(
        "/request/1",
        data={"_csrf": CSRF, "status": "In progress", "notes": hostile},
        follow_redirects=False,
    )
    assert r.status_code == 302
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT notes, status FROM requests WHERE id = ?", (1,)
    ).fetchone()
    conn.close()
    assert row[0] == hostile
    assert row[1] == "In progress"
    assert _row_count(db_path) == 1


def test_detail_route_rejects_non_integer_id(client):
    c, _ = client
    r = c.get("/request/1;DROP")
    assert r.status_code == 404
