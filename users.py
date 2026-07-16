"""User model and password handling.

Passwords are hashed with Werkzeug's PBKDF2. Never stored plaintext.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

VALID_ROLES = {"admin", "caseworker"}
MIN_PASSWORD_LEN = 12


def init_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            team TEXT NOT NULL,
            created_at TEXT NOT NULL,
            disabled_at TEXT
        )
        """
    )


@dataclass(frozen=True)
class User:
    id: int
    email: str
    role: str
    team: str
    disabled_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_user(
    conn: sqlite3.Connection,
    email: str,
    password: str,
    role: str,
    team: str,
) -> int:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role {role!r}; expected one of {sorted(VALID_ROLES)}")
    if not email or "@" not in email:
        raise ValueError("email is required and must contain '@'")
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if not team:
        raise ValueError("team is required")

    cur = conn.execute(
        "INSERT INTO users (email, password_hash, role, team, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            email.lower().strip(),
            generate_password_hash(password),
            role,
            team,
            _now(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_user_by_id(conn: sqlite3.Connection, user_id: int | str) -> User | None:
    row = conn.execute(
        "SELECT id, email, role, team, disabled_at FROM users WHERE id = ?",
        (int(user_id),),
    ).fetchone()
    if row is None:
        return None
    return User(id=row[0], email=row[1], role=row[2], team=row[3], disabled_at=row[4])


def authenticate(
    conn: sqlite3.Connection, email: str, password: str
) -> User | None:
    """Return the User on success, None on any failure.

    Callers must not distinguish between "no such user", "wrong
    password" and "account disabled" in messages shown to the client.
    """
    if not email or not password:
        return None
    row = conn.execute(
        "SELECT id, email, password_hash, role, team, disabled_at "
        "FROM users WHERE email = ?",
        (email.lower().strip(),),
    ).fetchone()
    if row is None:
        return None
    if row[5] is not None:  # disabled_at
        return None
    if not check_password_hash(row[2], password):
        return None
    return User(id=row[0], email=row[1], role=row[3], team=row[4])
