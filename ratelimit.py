"""Lightweight login rate limiter.

Counts `login.failure` rows in the audit trail within a rolling
window, keyed on the attempted email OR the source IP. Once the count
reaches the threshold, further attempts against that email or from
that IP are refused without checking the password.

Data source is `audit_events` — no separate table needed. The
audit trail is already the record of failed logins; using it here
means the rate limiter reads the same source of truth the ICO
auditor will.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

WINDOW_MINUTES = 15
MAX_FAILURES = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff_iso(now: datetime | None = None) -> str:
    cutoff = (now or _now()) - timedelta(minutes=WINDOW_MINUTES)
    return cutoff.isoformat(timespec="seconds")


def _normalise(email: str | None, ip: str | None) -> tuple[str | None, str | None]:
    e = email.lower().strip() if email else None
    if not e:
        e = None
    return e, ip or None


def failure_count(
    conn: sqlite3.Connection,
    *,
    email: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> int:
    """Return the number of failed-login events in the window that
    match the email OR the IP."""
    email, ip = _normalise(email, ip)
    if email is None and ip is None:
        return 0
    cutoff = _cutoff_iso(now)
    params: list = [cutoff]
    clauses: list[str] = []
    if email is not None:
        clauses.append("actor_email = ?")
        params.append(email)
    if ip is not None:
        clauses.append("ip = ?")
        params.append(ip)
    where = "action = 'login.failure' AND occurred_at >= ? AND (" + " OR ".join(clauses) + ")"
    row = conn.execute(
        f"SELECT COUNT(*) FROM audit_events WHERE {where}",  # nosec B608
        params,
    ).fetchone()
    return int(row[0]) if row else 0


def is_locked(
    conn: sqlite3.Connection,
    *,
    email: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> bool:
    return failure_count(conn, email=email, ip=ip, now=now) >= MAX_FAILURES


def seconds_until_unlock(
    conn: sqlite3.Connection,
    *,
    email: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> int:
    """Seconds until the oldest failure in the current window falls
    out of scope. Callers should send this as the `Retry-After` header.
    """
    email, ip = _normalise(email, ip)
    if email is None and ip is None:
        return 0
    cutoff = _cutoff_iso(now)
    params: list = [cutoff]
    clauses: list[str] = []
    if email is not None:
        clauses.append("actor_email = ?")
        params.append(email)
    if ip is not None:
        clauses.append("ip = ?")
        params.append(ip)
    where = "action = 'login.failure' AND occurred_at >= ? AND (" + " OR ".join(clauses) + ")"
    row = conn.execute(
        f"SELECT MIN(occurred_at) FROM audit_events WHERE {where}",  # nosec B608
        params,
    ).fetchone()
    if row is None or row[0] is None:
        return 0
    oldest = datetime.fromisoformat(row[0])
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    unlock_at = oldest + timedelta(minutes=WINDOW_MINUTES)
    delta = unlock_at - (now or _now())
    return max(1, int(delta.total_seconds()))
