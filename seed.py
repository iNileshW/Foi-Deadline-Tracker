"""Seed the FOI database with sample requests.

Usage:
    python seed.py [--db PATH] [--force] [--yes]

Semantics:
- No DB at `--db` path: create it and insert the sample rows.
- DB exists but contains no requests: initialise the schema and
  insert the sample rows.
- DB exists AND contains requests: refuse to run. Pass `--force` to
  wipe and reseed. `--force` alone still prompts on stdin; add
  `--yes` for scripted runs.

The old version deleted `foi.db` unconditionally on every invocation.
That is data loss waiting to happen the moment someone re-runs a
setup script against a live database.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta

from deadlines import calculate_deadline
from schema import init_all

SAMPLE = [
    # (ref, requester, subject, days_ago, status, team)
    ("FOI-2026-0141", "J. Whitfield", "Pothole repair spend by borough, 2024-2026", 38, "Responded", "roads"),
    ("FOI-2026-0152", "Roadside Truths blog", "Smart motorway incident response times", 31, "Responded", "roads"),
    ("FOI-2026-0159", "M. Osei", "Rail electrification feasibility studies since 2020", 27, "Internal review", "rail"),
    ("FOI-2026-0163", "Kent Online", "Correspondence about the Lower Thames Crossing", 24, "In progress", "roads"),
    ("FOI-2026-0170", "S. Brar", "EV charging point grant applications rejected in 2025", 19, "In progress", "roads"),
    ("FOI-2026-0174", "Cycling UK", "Active travel budget reallocations", 16, "In progress", "central"),
    ("FOI-2026-0178", "P. Lindqvist", "Ministerial meetings with airline lobbyists", 12, "In progress", "central"),
    ("FOI-2026-0181", "Transport Action Group", "Bus service improvement plan funding formula", 9, "Received", "rail"),
    ("FOI-2026-0183", "A. Ncube", "Driving test backlog by test centre", 6, "Received", "central"),
    ("FOI-2026-0185", "The Herald", "Costs of the pavement parking consultation", 3, "Received", "central"),
    ("FOI-2026-0186", "R. Kaminski", "Departmental spend on taxis, 2025", 1, "Received", "central"),
    ("FOI-2026-0187", "L. Fortescue", "Bridge inspection reports for the A38", 0, "Received", "roads"),
]


class SeedRefused(RuntimeError):
    """Raised when the caller has data at the target path and did not
    pass `force=True`, or when interactive confirmation was declined."""


def _has_requests(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) FROM requests").fetchone()
    return int(row[0]) > 0


def _insert_samples(conn: sqlite3.Connection) -> int:
    for ref, requester, subject, days_ago, status, team in SAMPLE:
        received = date.today() - timedelta(days=days_ago)
        deadline = calculate_deadline(received)
        conn.execute(
            "INSERT INTO requests "
            "(ref, requester, subject, received, deadline, status, notes, team) "
            "VALUES (?, ?, ?, ?, ?, ?, '', ?)",
            (ref, requester, subject, received.isoformat(), deadline.isoformat(), status, team),
        )
    conn.commit()
    return len(SAMPLE)


def seed(
    db_path: str,
    *,
    force: bool = False,
    yes: bool = False,
    confirmer=None,
) -> int:
    """Seed `db_path`. Returns the number of rows inserted.

    `confirmer(prompt) -> bool` is injectable for tests. In real use
    it's an `input()`-based prompt on stdin.
    """
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        init_all(conn)
        has_data = _has_requests(conn)
        conn.close()
        if has_data:
            if not force:
                raise SeedRefused(
                    f"{db_path} already contains requests. "
                    "Refusing to overwrite. "
                    "Back it up with `python backup.py foi.db backups` "
                    "and re-run with --force."
                )
            if not yes:
                if confirmer is None:
                    confirmer = _stdin_confirm
                if not confirmer(
                    f"WARNING: this will DELETE all data in {db_path}. "
                    "Type 'yes' to continue: "
                ):
                    raise SeedRefused("aborted by user")
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    try:
        init_all(conn)
        n = _insert_samples(conn)
    finally:
        conn.close()
    return n


def _stdin_confirm(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer == "yes"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Seed the FOI database with sample requests.",
    )
    p.add_argument(
        "--db", default=os.environ.get("FOI_DB", "foi.db"),
        help="Path to the SQLite database. Default: $FOI_DB or foi.db.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Wipe and reseed even if the target DB already has data.",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="Skip the interactive confirmation (use with --force in scripts).",
    )
    args = p.parse_args(argv[1:])

    try:
        n = seed(args.db, force=args.force, yes=args.yes)
    except SeedRefused as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Seeded {args.db} with {n} requests")
    print("No users created. Add one with: python create_user.py EMAIL ROLE TEAM")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
