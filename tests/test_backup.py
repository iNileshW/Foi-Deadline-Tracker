"""Backup and restore drill.

`test_restore_round_trip` is the one an auditor cares about: seed a
DB, back it up, mutate it, restore, and prove the mutation is gone
and the seeded state is back.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from audit import init_audit_table
from backup import _prune, backup_db
from restore import restore_db, verify_backup
from users import create_user, init_users_table


def _seed(path: Path) -> None:
    conn = sqlite3.connect(path)
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
        ("FOI-1", "Alice", "Bridges", "2026-04-02", "2026-05-05",
         "Received", ""),
    )
    init_users_table(conn)
    init_audit_table(conn)
    create_user(conn, "a@x.gov.uk", "correct-horse-battery", "caseworker", "central")
    conn.commit()
    conn.close()


def test_backup_creates_snapshot_and_manifest(tmp_path):
    src = tmp_path / "foi.db"
    _seed(src)
    dest = tmp_path / "backups"
    out = backup_db(src, dest, keep=5)
    assert out.exists()
    assert out.stat().st_size > 0
    manifest_path = dest / f"{out.stem}.manifest.json"
    assert manifest_path.exists()
    m = json.loads(manifest_path.read_text())
    assert len(m["sha256"]) == 64  # sha256 hex
    assert m["size_bytes"] == out.stat().st_size
    counts = m["table_counts"]
    assert counts["requests"] == 1
    assert counts["users"] == 1
    assert "audit_events" in counts


def test_backup_prune_keeps_only_N(tmp_path):
    src = tmp_path / "foi.db"
    _seed(src)
    dest = tmp_path / "backups"
    for i in range(5):
        backup_db(src, dest, keep=3, _now=f"tag-{i:03d}")
    dbs = sorted(dest.glob("foi-*.db"))
    manifests = sorted(dest.glob("foi-*.manifest.json"))
    assert len(dbs) == 3
    assert len(manifests) == 3
    # Oldest two dropped, newest three kept.
    assert [p.stem for p in dbs] == ["foi-tag-002", "foi-tag-003", "foi-tag-004"]


def test_backup_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_db(tmp_path / "nope.db", tmp_path / "backups")


def test_restore_round_trip(tmp_path):
    """The drill: seed → back up → mutate → restore → check."""
    src = tmp_path / "foi.db"
    _seed(src)
    dest = tmp_path / "backups"
    backup = backup_db(src, dest, keep=5)

    # Mutate the live DB.
    conn = sqlite3.connect(src)
    conn.execute(
        "INSERT INTO requests "
        "(ref, requester, subject, received, deadline, status, notes) "
        "VALUES ('R2','B','S2','2026-04-03','2026-05-06','Received','')"
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 2
    conn.close()

    # Restore.
    safety = restore_db(backup, src)
    assert safety is not None
    assert safety.exists()

    # Live DB is back to seeded state; safety copy holds the mutation.
    conn = sqlite3.connect(src)
    assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 1
    conn.close()

    conn = sqlite3.connect(safety)
    assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 2
    conn.close()


def test_restore_refuses_broken_backup(tmp_path):
    """A backup lacking the `requests` table must never overwrite prod."""
    bad = tmp_path / "bad.db"
    conn = sqlite3.connect(bad)
    conn.execute("CREATE TABLE other (x INT)")
    conn.commit()
    conn.close()

    target = tmp_path / "prod.db"
    _seed(target)
    original_size = target.stat().st_size

    with pytest.raises(ValueError, match="requests"):
        restore_db(bad, target)

    # Prod DB untouched.
    assert target.stat().st_size == original_size


def test_restore_creates_pre_restore_safety_copy(tmp_path):
    src = tmp_path / "foi.db"
    _seed(src)
    dest = tmp_path / "backups"
    backup = backup_db(src, dest, keep=5)

    conn = sqlite3.connect(src)
    conn.execute(
        "INSERT INTO requests (ref) VALUES ('MOD')"
    )
    conn.commit()
    conn.close()

    safety = restore_db(backup, src)
    assert safety is not None
    assert safety.exists()

    conn = sqlite3.connect(safety)
    n = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE ref = 'MOD'"
    ).fetchone()[0]
    conn.close()
    assert n == 1


def test_backup_uses_online_api_under_open_connection(tmp_path):
    """SQLite's online-backup API must not deadlock when the source
    already has an open connection — this is what makes it safer than
    `cp foi.db`."""
    src = tmp_path / "foi.db"
    _seed(src)
    holder = sqlite3.connect(src)
    try:
        holder.execute("SELECT 1").fetchall()
        out = backup_db(src, tmp_path / "backups", keep=5)
        conn = sqlite3.connect(out)
        assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 1
        conn.close()
    finally:
        holder.close()


def test_verify_backup_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_backup(tmp_path / "missing.db")


def test_restore_with_no_pre_existing_target(tmp_path):
    src = tmp_path / "foi.db"
    _seed(src)
    backup = backup_db(src, tmp_path / "backups")
    fresh = tmp_path / "recovered.db"
    safety = restore_db(backup, fresh)
    assert safety is None
    assert fresh.exists()


def test_manifest_sha256_matches_file(tmp_path):
    import hashlib
    src = tmp_path / "foi.db"
    _seed(src)
    dest = tmp_path / "backups"
    out = backup_db(src, dest, keep=5)
    manifest = json.loads((dest / f"{out.stem}.manifest.json").read_text())
    actual = hashlib.sha256(out.read_bytes()).hexdigest()
    assert manifest["sha256"] == actual
