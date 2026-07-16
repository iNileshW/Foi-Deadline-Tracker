"""Immutable audit trail for the FOI tracker.

Every mutating action writes an `audit_events` row. Rows are never
updated or deleted by the application code — they are what the ICO
auditor reads when they ask "who has accessed this requester's record?"
or "why did the status change on Thursday afternoon?"

Recorded actions (see `Action`):
  login.success, login.failure, logout,
  request.create, request.update

Columns:
  id              autoincrement
  occurred_at     UTC ISO-8601 with seconds
  actor_id        users.id, or NULL for pre-auth events (e.g. failed login)
  actor_email     denormalised so records survive user deletion
  action          one of the Action enum values
  target_type     'request', 'user', or NULL
  target_id       PK of the target row, or NULL
  before_json     JSON snapshot of the record BEFORE the change, or NULL
  after_json      JSON snapshot AFTER the change, or NULL
  ip              request.remote_addr
  user_agent      request.headers['User-Agent'], truncated
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

USER_AGENT_MAX = 255

# Action names are strings, not an Enum, so the SQL schema stays
# tool-friendly and easy to grep for.
ACTIONS = {
    "login.success",
    "login.failure",
    "login.blocked",   # rate-limiter refused the attempt without checking creds
    "logout",
    "request.create",
    "request.update",
    "request.view",  # reserved for later
}


def init_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            actor_id INTEGER,
            actor_email TEXT,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            before_json TEXT,
            after_json TEXT,
            ip TEXT,
            user_agent TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_target "
        "ON audit_events (target_type, target_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_actor "
        "ON audit_events (actor_id, occurred_at)"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str)


def record_event(
    conn: sqlite3.Connection,
    action: str,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    before: Any = None,
    after: Any = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> int:
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")
    if user_agent and len(user_agent) > USER_AGENT_MAX:
        user_agent = user_agent[:USER_AGENT_MAX]
    cur = conn.execute(
        "INSERT INTO audit_events "
        "(occurred_at, actor_id, actor_email, action, "
        " target_type, target_id, before_json, after_json, ip, user_agent) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _now(),
            actor_id,
            actor_email,
            action,
            target_type,
            target_id,
            _dump(before),
            _dump(after),
            ip,
            user_agent,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_events(
    conn: sqlite3.Connection,
    *,
    limit: int = 200,
    target_type: str | None = None,
    target_id: int | None = None,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    if target_type is not None and target_id is not None:
        return conn.execute(
            "SELECT * FROM audit_events "
            "WHERE target_type = ? AND target_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (target_type, target_id, int(limit)),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
