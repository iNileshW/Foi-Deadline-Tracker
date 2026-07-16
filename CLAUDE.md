# FOI Deadline Tracker — CLAUDE.md

Flask CRUD app tracking Freedom of Information requests for DfT central FOI team. Inherited prototype from hackathon Scenario 3. Goal: make production-grade before autumn ICO audit.

## Context

- 6 caseworkers use daily. Two more directorates joining → multi-team, personal data (requester names/addresses under UK GDPR).
- ICO audit incoming autumn 2026. Scope: deadline accuracy, data protection, access control, recoverability.
- One statutory FOIA breach already occurred: request received Thursday before Easter, deadline calc ignored bank holidays.

## Definition of Done

Pass an ICO auditor asking about: **deadline accuracy, data protection, access control, recoverability**. Prioritise the gap that matters most; defend the call.

## Known Defects

Fixed:
- ~~`deadlines.py:calculate_deadline` — weekends only, no bank holidays.~~ Fixed: GOV.UK feed cached to `bank_holidays.json`; 10 tests cover Easter, Christmas, day-zero rule.
- ~~SQL injection in `/`, `/new`, `/request/<id>`.~~ Fixed: all queries parameterised; 6 injection regression tests.
- ~~`secret_key = "dev"`, `debug=True` hardcoded.~~ Fixed: `FOI_SECRET_KEY` required from env; app refuses to start without it (dev flag `FOI_ALLOW_INSECURE_DEV_SECRET=1` for local only). Debug off by default; `FLASK_DEBUG=1` opts in.
- ~~No authentication, no per-user identity.~~ Fixed: session-based auth (`auth.py`, `users.py`); passwords hashed with Werkzeug PBKDF2; every route behind `@login_required`; CSRF on all state-changing requests; session id rotated on login; disabled-user flag honoured; 15 auth tests. Users created via `python create_user.py EMAIL ROLE TEAM`.
- ~~No audit log.~~ Fixed: append-only `audit_events` table (`audit.py`) records login success/failure, logout, request create/update. Each row: actor id + email, action, target, before/after JSON snapshots, IP, user agent, UTC timestamp. Admin-only `/audit` viewer. 13 audit tests including no-password-leak guard.
- ~~No RBAC.~~ Partial: `admin_required` decorator gates `/audit`. Role column consulted at request time.
- ~~`foi.db` backup = Gary's USB stick, Fridays, "usually".~~ Fixed: `backup.py` uses SQLite online-backup API (safe under concurrent writes), writes a manifest (sha256, size, table counts) beside each snapshot, prunes to keep-N. `restore.py` verifies the backup before overwriting and keeps a pre-restore safety copy. 10 backup/restore tests including a full round-trip drill. Off-machine copy is left to `rsync` / S3 sync by design.

- ~~No CI.~~ Fixed: `.github/workflows/ci.yml`. Three jobs — pytest across Python 3.11/3.12/3.13, bandit SAST + pip-audit on both requirements files, and a `main`-only tarball artifact. Deploy step deliberately not automated (no target env).

Still open:
- No team-based data separation on requests (`team` on users, not yet joined against a `team` column on requests).
- `seed.py:10-11` — deletes `foi.db` unconditionally on run. Destructive.
- No container.
- `requirements.txt` — unpinned `flask` only.
- No rate limiting on `/login`. Brute-force protection is on the to-do list.
- UK GDPR retention policy on requester name/address is undefined.

## Architecture

- `app.py` — Flask app, port 5002. Routes: `/`, `/new`, `/request/<id>`, `/login`, `/logout` (POST), `/audit` (admin-only). Global `before_request` verifies CSRF on all state-changing requests. Every mutating handler writes an `audit_events` row via `audit.record_event()`.
- `auth.py` — `login_required`, `admin_required`, `login_user` (rotates session), `logout_user`, CSRF token helpers.
- `audit.py` — `init_audit_table`, `record_event`, `list_events`; append-only trail with actor + before/after snapshots.
- `users.py` — `User` dataclass, `init_users_table`, `create_user`, `authenticate`, `get_user_by_id`. Passwords hashed with Werkzeug PBKDF2.
- `deadlines.py` — `calculate_deadline(received: date) -> date`, 20 working days, holiday-aware.
- `seed.py` — recreates `foi.db` with sample rows and the users table.
- `create_user.py` — CLI to add users (password read from terminal).
- `templates/` — `base.html`, `index.html`, `new.html`, `detail.html`, `login.html`.
- `foi.db` — SQLite. Tables:
  - `requests(id, ref, requester, subject, received, deadline, status, notes)`
  - `users(id, email UNIQUE, password_hash, role, team, created_at, disabled_at)`
  - `audit_events(id, occurred_at, actor_id, actor_email, action, target_type, target_id, before_json, after_json, ip, user_agent)`
- Statuses: `Received`, `In progress`, `Internal review`, `Responded`, `Overdue`.
- Roles: `admin`, `caseworker`.

## Run

```
pip install -r requirements.txt
python seed.py    # WIPES foi.db
python app.py     # http://localhost:5002
```

## Priority Directions (from brief)

1. **Correctness** — fix deadline with GOV.UK bank holidays API (`https://www.gov.uk/bank-holidays.json`, `england-and-wales` division). Test suite: Easter, Christmas, request received on bank holiday, ICO day-counting rules.
2. **Security** — parameterised queries, real secret via env, auth + per-user accounts, audit log of record changes.
3. **Operations** — deployment story off Gary's desktop, automated backups, **proven restore**.
4. **Data protection** — UK GDPR retention policy, access control on requester PII, deletion-request handling.
5. **CI pipeline** — tests on every change, security scan, deploy step.
6. **Ops features** — deadline-approaching email alerts, exceptions report, annual FOI-return stats, multi-team data separation.

## Rules of Engagement

- ICO day-counting: statutory 20 working days. Working day = not Sat/Sun and not England-and-Wales bank holiday. Day of receipt is day zero (verify against ICO guidance before locking in).
- Personal data = requester `name` + `address` fields. Access control + audit log required.
- No API keys needed. Bank holidays API is public JSON.
- Machine may lack Docker/Git — containerisation and VCS are directions, not prerequisites.

## Starting Points

- GOV.UK bank holidays API: `https://www.gov.uk/bank-holidays.json`
- ICO guidance: time limits for FOI compliance
- OWASP SQL injection prevention cheat sheet
- GDS Way

## Test Questions (must be able to answer)

1. Request arrives Maundy Thursday — what deadline does current code give, what's correct, what test proves the fix?
2. What can the search box do today? Demo safely, then close it.
3. Auditor asks "who accessed this requester's record?" — answer before vs. after.
4. Gary's machine dies Wednesday — walk the recovery, before vs. after.

## Deliverables

- End Day 1 (5 min): priority call — audit findings, what you picked, progress.
- End Day 2 (10 min): what shipped. Prototype vs. handed-back system. Honest "next if we had Day 3".
