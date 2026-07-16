"""Single entry point for DB schema init and column migrations.

Every process that opens the FOI database should call `init_all()`.
All operations are idempotent — `CREATE TABLE IF NOT EXISTS` plus a
`PRAGMA table_info` check before `ALTER TABLE ADD COLUMN`.

Keeping the schema in one place means seed.py, app.py's `get_db()`,
and any future migration script agree on the shape of the tables.
"""

from __future__ import annotations

import sqlite3

from audit import init_audit_table
from users import init_users_table


def init_requests_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT,
            requester TEXT,
            subject TEXT,
            received TEXT,
            deadline TEXT,
            status TEXT,
            notes TEXT,
            team TEXT NOT NULL DEFAULT '',
            responded_at TEXT,
            pii_redacted_at TEXT
        )
        """
    )
    _ensure_column(
        conn, "requests", "team",
        "ALTER TABLE requests ADD COLUMN team TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(
        conn, "requests", "responded_at",
        "ALTER TABLE requests ADD COLUMN responded_at TEXT",
    )
    _ensure_column(
        conn, "requests", "pii_redacted_at",
        "ALTER TABLE requests ADD COLUMN pii_redacted_at TEXT",
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(ddl)


def init_all(conn: sqlite3.Connection) -> None:
    init_requests_table(conn)
    init_users_table(conn)
    init_audit_table(conn)
