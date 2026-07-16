"""UK GDPR retention: purge requester PII once a case is old enough.

Policy (default): 3 years (1095 days) after a request is responded
to, the requester's name and free-text notes are redacted. Case
metadata (ref, subject, dates, status, deadline, team) is retained
so the department can still answer statistical questions and pass
its FOI-return numbers to the Cabinet Office.

Trigger paths:
- **Scheduled**: `python retention.py` — every request whose
  `responded_at` is older than the retention window is redacted.
  `--dry-run` shows candidates without touching data.
- **On-demand (right-to-erasure / DSAR)**: an admin `POST` to
  `/request/<id>/erase-pii` calls `redact_request` directly.

Redaction is not deletion. `pii_redacted_at` is set so we know the
row has been through this process; an audit-trail row records who
did what and why. Redacting the same row twice is a no-op.

Configurable via `FOI_RETENTION_DAYS`.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DEFAULT_RETENTION_DAYS = 1095
REDACTED = "[REDACTED]"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def find_due(
    conn: sqlite3.Connection,
    days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
) -> list[sqlite3.Row]:
    """Rows whose PII should be redacted under the retention policy."""
    now = now or _now()
    cutoff = (now - timedelta(days=days)).date().isoformat()
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM requests "
        "WHERE status = 'Responded' "
        "  AND responded_at IS NOT NULL "
        "  AND responded_at <= ? "
        "  AND pii_redacted_at IS NULL "
        "ORDER BY id",
        (cutoff,),
    ).fetchall()


def redact_request(
    conn: sqlite3.Connection,
    req_id: int,
    *,
    actor=None,
    reason: str = "retention-policy",
    now: datetime | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> bool:
    """Redact `requester` and `notes` in place. Returns True on
    change, False if the row is missing or already redacted."""
    from audit import record_event  # avoid an import cycle at module load

    conn.row_factory = sqlite3.Row
    before = conn.execute(
        "SELECT * FROM requests WHERE id = ?", (req_id,)
    ).fetchone()
    if before is None:
        return False
    if before["pii_redacted_at"]:
        return False

    now_iso = (now or _now()).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE requests "
        "SET requester = ?, notes = ?, pii_redacted_at = ? "
        "WHERE id = ?",
        (REDACTED, REDACTED, now_iso, req_id),
    )
    conn.commit()

    after = conn.execute(
        "SELECT * FROM requests WHERE id = ?", (req_id,)
    ).fetchone()

    after_dict = dict(after)
    after_dict["_reason"] = reason
    record_event(
        conn,
        "request.erase_pii",
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        target_type="request",
        target_id=req_id,
        before=dict(before),
        after=after_dict,
        ip=ip,
        user_agent=user_agent,
    )
    return True


def purge_due(
    conn: sqlite3.Connection,
    days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
    actor=None,
    dry_run: bool = False,
) -> list[int]:
    """Redact everything currently due. Returns the list of ids
    touched (empty list for dry-run)."""
    due = find_due(conn, days, now)
    if dry_run:
        return []
    redacted: list[int] = []
    for row in due:
        if redact_request(
            conn, int(row["id"]), actor=actor, reason="retention-policy", now=now
        ):
            redacted.append(int(row["id"]))
    return redacted


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Redact requester PII on FOI requests past their "
                    "retention window.",
    )
    parser.add_argument(
        "--days", type=int,
        default=int(os.environ.get("FOI_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)),
        help="Retention window in days. Default: 1095 (3 years).",
    )
    parser.add_argument(
        "--db", default=os.environ.get("FOI_DB", "foi.db"),
        help="SQLite database path.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report candidates without modifying anything.",
    )
    args = parser.parse_args(argv[1:])

    from schema import init_all
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        init_all(conn)
        if args.dry_run:
            due = find_due(conn, args.days)
            for r in due:
                print(f"DUE id={r['id']} ref={r['ref']} responded_at={r['responded_at']}")
            print(f"total due: {len(due)}")
        else:
            redacted = purge_due(conn, args.days)
            print(f"redacted {len(redacted)} row(s): {redacted}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
