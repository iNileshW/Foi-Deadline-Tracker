# FOI Deadline Tracker

[![CI](https://github.com/iNileshW/Foi-Deadline-Tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/iNileshW/Foi-Deadline-Tracker/actions/workflows/ci.yml)

Tracks Freedom of Information requests for the DfT central FOI team and
calculates the statutory 20-working-day response deadline.

Replaced the old spreadsheet in March. The team likes it. Two other
directorates have asked for accounts, and someone mentioned the ICO audit
happening in the autumn.

**Status:** in daily use by 6 people. Runs on Gary's old desktop under
his desk. If it's down, ask Gary to turn his machine back on.

## Running it

```
pip install -r requirements.txt
python seed.py       # creates foi.db with sample data
                     # refuses to run if foi.db already has requests; pass --force --yes to reseed
python create_user.py alice@example.gov.uk caseworker central  # prompts for password

# Production: set a real secret.
export FOI_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')

# Local development shortcut (ephemeral secret, sessions don't survive restart):
# export FOI_ALLOW_INSECURE_DEV_SECRET=1

python app.py
```

Sign in at http://localhost:5002/login with the account you just created.

Then open http://localhost:5002

## Configuration

| Env var | Purpose | Default |
| --- | --- | --- |
| `FOI_SECRET_KEY` | Flask session secret. **Required** unless dev override set. | — |
| `FOI_ALLOW_INSECURE_DEV_SECRET` | If `1`, generate an ephemeral secret when `FOI_SECRET_KEY` is unset. Local dev only. | unset |
| `FLASK_DEBUG` | Set to `1` to enable Werkzeug debugger. Do not enable in production. | `0` |
| `FOI_DB` | Path to the SQLite database file. | `foi.db` |
| `PORT` | HTTP port. | `5002` |
| `FOI_SECURE_COOKIES` | Set to `1` to mark the session cookie `Secure` (HTTPS-only). Enable in production. | `0` |

See `.env.example`.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Security scans (local)

CI runs the same checks on every push and pull request via
`.github/workflows/ci.yml`.

```
pip install bandit pip-audit
bandit -r . -x ./tests,./templates,./.github,./backups -ll
pip-audit --strict -r requirements.txt
pip-audit --strict -r requirements-dev.txt
```

## CI

Four jobs, GitHub Actions:

- **Tests** — pytest across Python 3.11 / 3.12 / 3.13.
- **Security scans** — bandit SAST and pip-audit on both requirements files.
- **Docker build** — builds the image on every push and pull request so a
  broken Dockerfile is caught before merge.
- **Package** — on merges to `main`, uploads a timestamped tarball artifact
  (30-day retention). Deploy is deliberately not automated — no shared
  target environment yet.

## Container

```
docker compose up --build
```

App on http://localhost:5002. Data persists in the `foi_data` volume so a
`docker compose down && docker compose up` retains the database.

First run — seed the DB and add a user:

```
docker compose exec foi python seed.py
docker compose exec foi python create_user.py admin@dft.gov.uk admin central
```

Runtime notes:

- Serves under **gunicorn**, not the Flask dev server. Two workers by
  default; set `WEB_CONCURRENCY=N` in `.env` to scale.
- Runs as a non-root user (UID 10001).
- Health probe: `GET /healthz` — returns 200 when the DB opens and the
  three schema-critical tables (`requests`, `users`, `audit_events`) are
  present, 503 otherwise. Docker HEALTHCHECK polls it every 30 s.
- `FOI_SECRET_KEY` must be set in production. Local development can use
  `FOI_ALLOW_INSECURE_DEV_SECRET=1` (already default in `docker-compose.yml`
  via env passthrough).

## Backup and restore

The tracker uses SQLite's online backup API — safe under concurrent
writes, unlike `cp foi.db` which can capture a torn transaction.

Take a snapshot:

```
python backup.py foi.db backups 14
```

- Writes `backups/foi-<UTC-timestamp>.db` and a matching
  `.manifest.json` (sha256, size, per-table row counts).
- Prunes to the newest 14 snapshots. Pass a different number to change
  retention, or 0 to disable pruning.

Schedule it. Simplest option — a cron entry running every hour:

```
0 * * * * cd /path/to/foi-tracker && /usr/bin/python3 backup.py foi.db backups 168 >> backups/backup.log 2>&1
```

**Off-machine copy is your responsibility.** Point `rsync`, an S3
sync, or your approved transport at the `backups/` directory. A
snapshot on the same disk as the source is not a backup.

### Restore drill

```
python restore.py backups/foi-<timestamp>.db foi.db
```

- Refuses to overwrite `foi.db` if the backup lacks a `requests`
  table (a corrupt or wrong-file mistake).
- Copies the current `foi.db` aside as
  `foi.db.pre-restore-<UTC-timestamp>` before overwriting, so a
  botched restore is reversible.
- Uses a `.restore-tmp` intermediate + rename, so a concurrently
  running app never reads a half-copied file.

Run the drill at least monthly. A backup no-one has restored is a
hypothesis.

## UK GDPR retention

Requester name and free-text notes are personal data. Under UK GDPR
they must not be kept longer than necessary. Case metadata (ref,
subject, dates, status, deadline, team) is not personal data and is
retained to support the annual FOI return.

Default retention window: **3 years (1095 days) after a request is
marked Responded**. Configurable via `FOI_RETENTION_DAYS`.

### Scheduled purge

```
python retention.py --dry-run   # list candidates
python retention.py             # redact due rows
```

Cron example (weekly, Sunday 03:00):

```
0 3 * * 0 cd /path/to/foi-tracker && /usr/bin/python3 retention.py >> retention.log 2>&1
```

Each redaction writes a `request.erase_pii` row to the audit trail —
timestamp, actor id, before/after JSON, IP, user agent. Idempotent:
rerunning is a no-op on rows that have already been redacted.

### Right to erasure (DSAR)

An admin can trigger redaction on demand from the request detail page
(`POST /request/<id>/erase-pii`). Reason is captured in the audit
trail and shown to future readers of the record.

Redaction is intentionally not deletion — the row is retained with a
`pii_redacted_at` timestamp so the audit trail remains coherent.

## Notes

- Deadlines are 20 working days from receipt (weekends excluded).
- The search box was added quickly for the team — it matches subject
  or requester name.
- Everyone shares the same screen, no logins. It's internal so fine.
- Backups: Gary copies foi.db to a USB stick on Fridays, usually.
