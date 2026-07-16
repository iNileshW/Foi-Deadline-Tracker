"""Online SQLite backup with manifest + retention.

Usage:
    python backup.py SRC_DB DEST_DIR [KEEP]

Uses SQLite's online-backup API (`conn.backup(target)`) so the backup
is atomic and safe under concurrent writes — unlike a raw file copy,
which can capture a torn database mid-transaction.

Every backup produces two files in `DEST_DIR`:
    foi-<timestamp>.db              — the snapshot
    foi-<timestamp>.manifest.json   — metadata (sha256, table counts)

The manifest is the auditor's evidence that the backup was consistent
at time of writing. `KEEP` defaults to 14; older snapshots (and their
manifests) are pruned automatically.

Off-machine copy is out of scope for this script — pipe the backup
directory to `rsync`, `aws s3 sync`, or your organisation's approved
transport.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_KEEP = 14


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _table_counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
            for n in names
        }
    finally:
        conn.close()


def _timestamp() -> str:
    # Microsecond resolution so back-to-back calls never collide.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def backup_db(
    src: str | Path,
    dest_dir: str | Path,
    keep: int = DEFAULT_KEEP,
    *,
    _now: str | None = None,
) -> Path:
    """Snapshot `src` into `dest_dir` and prune old snapshots.

    Returns the path to the new snapshot.
    """
    src = Path(src)
    dest_dir = Path(dest_dir)
    if not src.exists():
        raise FileNotFoundError(src)
    dest_dir.mkdir(parents=True, exist_ok=True)

    ts = _now or _timestamp()
    dst = dest_dir / f"foi-{ts}.db"
    manifest_path = dest_dir / f"foi-{ts}.manifest.json"

    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_path": str(src),
        "backup_path": str(dst),
        "sha256": _sha256(dst),
        "size_bytes": dst.stat().st_size,
        "table_counts": _table_counts(dst),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    _prune(dest_dir, keep)
    return dst


def _prune(dest_dir: Path, keep: int) -> None:
    if keep <= 0:
        return
    dbs = sorted(dest_dir.glob("foi-*.db"))
    for old in dbs[:-keep]:
        old.unlink(missing_ok=True)
        (dest_dir / f"{old.stem}.manifest.json").unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    if len(argv) < 3 or len(argv) > 4:
        print(__doc__, file=sys.stderr)
        return 2
    src, dest = argv[1], argv[2]
    keep = int(argv[3]) if len(argv) == 4 else DEFAULT_KEEP
    try:
        dst = backup_db(src, dest, keep)
    except FileNotFoundError as e:
        print(f"error: source database not found: {e}", file=sys.stderr)
        return 1
    print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
