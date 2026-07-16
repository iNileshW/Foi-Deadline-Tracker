# FOI Deadline Tracker — Shipped

A snapshot of everything shipped against the Production Hackathon
Scenario 3 brief, ready for the Day-2 presentation.

## Starting state (inherited)

- Flask CRUD app, SQLite, dev server on Gary's desktop.
- Deadline calc: weekends only, no bank holidays → known statutory
  breach (Maundy Thursday case cited in the brief).
- Every SQL query built by f-string on user input.
- `secret_key = "dev"`, `debug=True` hardcoded.
- No authentication, no audit log, no rate limiting.
- Backup = Friday USB stick.
- Zero tests, zero CI.
- `seed.py` unconditionally `rm foi.db`.

## Commits on `main` (chronological)

| # | Commit | Change |
| --- | ------ | ------ |
| 1 | `01fb753` | Deadline calc + SQL-injection fix + 16 tests |
| 2 | `780a009` | `FOI_SECRET_KEY` env; kill `debug=True` |
| 3 | `3671641` | Session auth, CSRF, users table + idempotent-schema hotfix |
| 4 | `148b57c` | Log docs |
| 5 | `60bccc9` | Append-only audit trail + admin `/audit` view |
| 6 | `bdda212` | SQLite online-backup + verified restore + drill |
| 7 | `814a78d` | GitHub Actions CI (test / bandit / pip-audit / package) |
| 8 | `31bedbb` | Containerise: Dockerfile, compose, gunicorn, `/healthz` |
| 9 | `91bfc22` | Rate-limit `/login` (5/15 min, email OR IP, 429 + Retry-After) |
| 10 | `a7f1628` | Team-based data separation (`team` column + scope + migration) |
| 11 | `1e6ef33` | UK GDPR retention (3-yr purge, admin DSAR route) |
| 12 | `2ccdfea` | Pin every runtime + dev dep (reproducible builds) |
| 13 | `f0ea17a` | Backfill `team` on seed rows |
| 14 | `ced59eb` | Kill destructive `seed.py` (`--force --yes` gated) |

## Evidence

- **112 pytest tests** across 11 files:
  - `test_deadlines` (10)
  - `test_sql_injection` (6)
  - `test_config` (6)
  - `test_auth` (15)
  - `test_audit` (13)
  - `test_backup` (10)
  - `test_healthz` (3)
  - `test_ratelimit` (13)
  - `test_team_scope` (12)
  - `test_retention` (15)
  - `test_seed` (9)
- **Bandit**: 0 findings, 5 `# nosec` annotations with in-source reasons.
- **pip-audit**: 0 known vulnerabilities on both requirements files.
- **CI** (`.github/workflows/ci.yml`): pytest matrix 3.11 / 3.12 / 3.13,
  bandit, pip-audit, docker build, `main`-only tarball artifact
  (30-day retention).
- **Container**: gunicorn, non-root UID 10001, `/healthz` liveness
  probe, `/data` volume. Live end-to-end verified — 12 rows visible
  after seed, login round-trip returns 200.
- **Backup/restore drill**: `foi-<UTC-ts>.db` snapshot plus manifest
  (sha256, size, per-table row counts). Live round-trip drill
  against the real `foi.db` confirmed the mutation disappears and
  the pre-restore safety copy is preserved.

## ICO audit mapping

| Axis | Before | After |
| ---- | ------ | ----- |
| **Deadline accuracy** | Weekend-only skip; breach recorded | GOV.UK bank-holiday feed cached locally; 10 tests; Maundy Thu 2026 → 2026-05-05 (was 2026-04-30) |
| **Access control** | None | Session auth + CSRF + session rotation on login + rate limit + admin RBAC + team scoping |
| **Data protection** | Requester PII visible to every logged-in user | Team-scoped visibility, append-only audit trail, 3-year retention purge, admin-only DSAR erasure route |
| **Recoverability** | Friday USB, hopeful | Hourly online-backup snapshots + manifests + verified restore + pre-restore safety copies. Drill run in tests. |
| **Ops maturity** | Dev server on desktop, no CI | Container + gunicorn + `/healthz` + CI + reproducible builds |

## Brief probe answers

### Q1. Maundy Thursday scenario

Request received `2026-04-02` (Maundy Thursday).

- Old code: deadline `2026-04-30` (skipped weekends only; treated
  Good Friday, Easter Monday, Early May bank holiday as working
  days). This is the statutory breach the brief describes.
- Correct code: deadline `2026-05-05`.
- Test that proves it: `tests/test_deadlines.py::test_maundy_thursday_2026_scenario`.
- Regression guard against the old behaviour:
  `tests/test_deadlines.py::test_maundy_thursday_vs_weekend_only_differs`.

### Q2. What could the search box do?

Everything an unparameterised `LIKE '%…%' OR …'%'` allowed:
`'; DROP TABLE requests; --`,
`%' UNION SELECT sql,… FROM sqlite_master --`.
Every query now uses `?` parameter binding.
Tests: `tests/test_sql_injection.py`.

### Q3. Who accessed this requester's record?

Before: unknowable — no auth, no audit trail.
After:
```sql
SELECT * FROM audit_events
WHERE target_type = 'request' AND target_id = ?
ORDER BY id DESC;
```
Every row carries `actor_id`, `actor_email`, `action`, before /
after JSON snapshots, IP, User-Agent, UTC timestamp. Login attempts
(success / failure / blocked) and PII redactions are recorded on
the same table. Actions logged: `login.success`, `login.failure`,
`login.blocked`, `logout`, `request.create`, `request.update`,
`request.erase_pii`.

### Q4. Gary's Wednesday recovery

Before: hope Gary's Friday USB is intact and reachable.

After:
```bash
python restore.py backups/foi-<UTC-timestamp>.db foi.db
```
Restore verifies the backup opens and has the `requests` table
before touching anything, copies the current `foi.db` aside as
`foi.db.pre-restore-<UTC>`, writes through a `.restore-tmp` +
atomic rename. Cron entry in `README.md` runs `backup.py` hourly.
Test: `tests/test_backup.py::test_restore_round_trip`.

## What's still open

Nice-to-have, not audit-blocking:

- Admin UI to reassign a request's team (currently only via SQL).
- Off-machine backup transport (documented via rsync / S3 sync in
  `README.md`; deliberately not baked in — every org's approved
  transport differs).

## If we had a third day

- Wire an admin UI for team reassignment and disable-user actions.
- Structured logs → an aggregator so the audit trail is queryable
  outside the app.
- Reverse-proxy TLS + `FOI_SECURE_COOKIES=1` in the compose file
  for a production-shaped deploy.
- Alembic (or equivalent) migrations so the ad-hoc `_ensure_column`
  pattern in `schema.py` scales past three columns.
