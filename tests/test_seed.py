"""seed.py must refuse to destroy existing data.

Old version: unconditional `os.remove(DB)` on every invocation.
New version: refuses to run over a DB that already contains
requests unless `--force --yes` is passed.
"""

import sqlite3

import pytest

from seed import SAMPLE, SeedRefused, seed


def _count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    finally:
        conn.close()


def test_seeds_fresh_install(tmp_path):
    db = tmp_path / "foi.db"
    n = seed(str(db))
    assert n == len(SAMPLE)
    assert _count(db) == len(SAMPLE)


def test_seeds_empty_db(tmp_path):
    """A DB that exists but has no rows is safe to seed."""
    db = tmp_path / "foi.db"
    # Create an empty file with schema but no rows.
    conn = sqlite3.connect(db)
    from schema import init_all
    init_all(conn)
    conn.close()
    assert _count(db) == 0

    n = seed(str(db))
    assert n == len(SAMPLE)


def test_refuses_when_data_present(tmp_path):
    db = tmp_path / "foi.db"
    seed(str(db))
    # Second call without flags must refuse.
    with pytest.raises(SeedRefused, match="already contains requests"):
        seed(str(db))
    # And leave the data alone.
    assert _count(db) == len(SAMPLE)


def test_force_alone_still_prompts(tmp_path):
    db = tmp_path / "foi.db"
    seed(str(db))
    # confirmer returns False → aborted.
    with pytest.raises(SeedRefused, match="aborted by user"):
        seed(str(db), force=True, confirmer=lambda _prompt: False)
    assert _count(db) == len(SAMPLE)


def test_force_and_yes_wipes(tmp_path):
    db = tmp_path / "foi.db"
    seed(str(db))
    # Manually add a row that the reseed should NOT preserve.
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO requests (ref, requester, subject, received, deadline, status, notes, team) "
        "VALUES ('CUSTOM', 'x', 'x', '2026-01-01', '2026-02-01', 'Received', '', 'central')"
    )
    conn.commit()
    conn.close()
    assert _count(db) == len(SAMPLE) + 1

    n = seed(str(db), force=True, yes=True)
    assert n == len(SAMPLE)
    conn = sqlite3.connect(db)
    custom_present = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE ref = 'CUSTOM'"
    ).fetchone()[0]
    conn.close()
    assert custom_present == 0


def test_force_with_confirmer_returning_true(tmp_path):
    db = tmp_path / "foi.db"
    seed(str(db))
    n = seed(str(db), force=True, confirmer=lambda _p: True)
    assert n == len(SAMPLE)


def test_cli_refuses_over_existing_data(tmp_path):
    from seed import main
    db = tmp_path / "foi.db"
    seed(str(db))
    rc = main(["seed.py", "--db", str(db)])
    assert rc == 1
    assert _count(db) == len(SAMPLE)


def test_cli_fresh_install_succeeds(tmp_path):
    from seed import main
    db = tmp_path / "foi.db"
    rc = main(["seed.py", "--db", str(db)])
    assert rc == 0
    assert _count(db) == len(SAMPLE)


def test_cli_force_yes_wipes(tmp_path):
    from seed import main
    db = tmp_path / "foi.db"
    seed(str(db))
    rc = main(["seed.py", "--db", str(db), "--force", "--yes"])
    assert rc == 0
    assert _count(db) == len(SAMPLE)
