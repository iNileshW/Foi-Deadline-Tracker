"""Restore a SQLite backup into the target database path.

Usage:
    python restore.py BACKUP_DB TARGET_DB

Steps:
1. Verify the backup opens and has the expected `requests` table.
   A backup that fails this check is refused — better to keep the
   broken production DB than to silently overwrite it with garbage.
2. If TARGET_DB already exists, copy it aside as
       TARGET_DB.pre-restore-<UTC-timestamp>
   so a botched restore can be undone.
3. Copy the backup to `TARGET_DB.restore-tmp` and atomically rename
   over TARGET_DB. This avoids a half-copied file being read by a
   racing process.

This script does not run migrations. Restore to an app version that
matches the backup schema.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def verify_backup(path: str | Path) -> None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    if "requests" not in tables:
        raise ValueError(
            f"backup missing 'requests' table: {path}"
        )


def restore_db(
    backup_path: str | Path,
    target_path: str | Path,
    safety_dir: str | Path | None = None,
) -> Path | None:
    """Replace `target_path` with `backup_path`.

    Returns the path to the pre-restore safety copy, or None if there
    was no pre-existing target to preserve.
    """
    backup_path = Path(backup_path)
    target_path = Path(target_path)
    verify_backup(backup_path)

    safety: Path | None = None
    if target_path.exists():
        safety_dir_p = Path(safety_dir) if safety_dir else target_path.parent
        safety_dir_p.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safety = safety_dir_p / f"{target_path.name}.pre-restore-{ts}"
        shutil.copy2(target_path, safety)

    tmp = target_path.with_suffix(target_path.suffix + ".restore-tmp")
    shutil.copy2(backup_path, tmp)
    tmp.replace(target_path)
    return safety


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        safety = restore_db(argv[1], argv[2])
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if safety:
        print(f"restored. pre-restore safety copy: {safety}")
    else:
        print("restored (no pre-existing target to preserve).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
