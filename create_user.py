"""Create a user in foi.db.

Usage:
    python create_user.py EMAIL ROLE TEAM
Password is read from the terminal (not echoed).
"""

import getpass
import os
import sqlite3
import sys

from users import create_user, init_users_table

DB = os.environ.get("FOI_DB", "foi.db")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    email, role, team = argv[1], argv[2], argv[3]
    pw1 = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Confirm:  ")
    if pw1 != pw2:
        print("passwords do not match", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB)
    try:
        init_users_table(conn)
        try:
            uid = create_user(conn, email, pw1, role, team)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except sqlite3.IntegrityError:
            print(f"error: user {email!r} already exists", file=sys.stderr)
            return 1
    finally:
        conn.close()
    print(f"created user id={uid} email={email} role={role} team={team}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
