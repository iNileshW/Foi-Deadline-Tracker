# AI Change Log

Chronological record of AI-assisted changes to the FOI Deadline Tracker.
Newest entries appended at the bottom. Each entry: date, goal, files
touched, rationale, verification.

---

## 2026-07-16 — Bootstrap: CLAUDE.md

**Goal:** Give future AI sessions a grounded briefing.

**Files:**
- `CLAUDE.md` (new)

**Rationale:** Prototype inherited with no project doc for AI collaborators.
CLAUDE.md captures the ICO-audit definition of done, the known defects
with file:line references, the architecture, the run steps, and the
priority directions from the hackathon brief.

**Verification:** Cross-checked defect list against `app.py`, `deadlines.py`,
`seed.py`, `README.md`.

---

## 2026-07-16 — Fix statutory deadline calculation (bank holidays)

**Goal (set via `/goal`):** fix the deadline calculation first.

**Files:**
- `deadlines.py` (rewritten)
- `bank_holidays.json` (new — cached GOV.UK feed)
- `tests/__init__.py` (new)
- `tests/test_deadlines.py` (new — 10 tests)
- `requirements-dev.txt` (new — adds pytest)

**Rationale:** Old `calculate_deadline` skipped Sat/Sun only. Bank holidays
counted as working days, which produced deadlines earlier than the ICO
rule and caused the statutory breach cited in the brief (request received
Maundy Thursday 2026-04-02: old code returned 2026-04-30; correct
deadline per FOIA s10(6) + ICO guidance is 2026-05-05, three working days
later).

**Design choices:**
- Bank-holiday list sourced from `https://www.gov.uk/bank-holidays.json`,
  division `england-and-wales`.
- Feed cached to `bank_holidays.json` on disk so the app and tests run
  offline. `load_bank_holidays(refresh=True)` re-fetches on demand.
- `calculate_deadline(received, holidays=None)` — `holidays` is
  dependency-injectable for tests; production callers keep the original
  one-arg signature.
- Count starts the working day after receipt (day 0 = receipt itself).
  Deadline is the 20th such working day.

**Test coverage:**
- `test_maundy_thursday_2026_scenario` — the brief's breach case.
- `test_maundy_thursday_vs_weekend_only_differs` — regression guard vs.
  the old behaviour (asserts both old and new expected dates).
- `test_no_holidays_in_window` — clean 20-working-day window.
- `test_received_on_weekend_clock_starts_monday`.
- `test_received_on_bank_holiday`.
- `test_christmas_window_2026` — Christmas Day + Boxing Day substitute.
- `test_easter_2025` — separate year to guard year-specific bugs.
- `test_ico_day_zero_rule` — receipt date not counted.
- `test_deadline_is_always_a_working_day` — invariant across a
  60-day sweep of receipt dates.
- `test_holidays_none_uses_cached_file` — offline cache smoke test.

**Verification:** `python3 -m pytest tests/ -v` → 10 passed in 0.02s.

**Follow-ups (not done here):**
- Existing `foi.db` still holds deadlines computed under the old logic.
  Reseed with `python seed.py` (destructive — flagged separately in
  CLAUDE.md as a seed-script defect).
- `seed.py` and `app.py` unchanged; both call `calculate_deadline`
  with the same signature so no callers were broken.

---

## 2026-07-16 — Fix SQL injection across all four query sites

**Goal:** fix the SQL injection next.

**Files:**
- `app.py` (rewritten queries)
- `tests/test_sql_injection.py` (new — 6 tests)

**Rationale:** Every query in the inherited `app.py` interpolated user
input into the SQL string with f-strings. The search box on `/` was the
most obvious vector, but `POST /new`, `POST /request/<id>` and
`GET /request/<id>` were equally exposed. Under the ICO audit, an
auditable, injection-free query path is table-stakes for both data
protection and integrity.

**Changes to `app.py`:**
- `/` search: `LIKE ? OR LIKE ?` with the `%q%` wrapping done in
  Python, values passed as `execute()` parameters.
- `/new` INSERT: seven-column parameter tuple; status literal
  stays inline.
- `/request/<int:req_id>` UPDATE and SELECT: `?` placeholders for
  status, notes, and id.
- Removed the "quick search feature" and "change this at some point"
  comments — they were project archaeology, not code documentation.
  Left one `TODO` marker on the dev `secret_key` because that's the
  next security fix.

**Route-level defence retained:** `/request/<int:req_id>` still uses
Flask's `int` path converter, so a path such as `/request/1;DROP` 404s
before the view function runs. A dedicated test locks that in.

**Test coverage (all against a per-test throwaway SQLite DB via a
`monkeypatch` fixture):**
- `test_search_drop_table_neutralised` — classic `'; DROP TABLE …; --`
  payload; row count remains 1 afterwards.
- `test_search_union_leak_neutralised` — `%' UNION SELECT sql,… FROM
  sqlite_master --` payload; response contains neither schema text nor
  the seeded row.
- `test_search_literal_apostrophe_is_safe` — a bare apostrophe used to
  crash the query; now returns 200 with an empty result set.
- `test_new_request_persists_apostrophes` — `O'Brien`, mixed quotes and
  semicolons round-trip intact through the INSERT path.
- `test_detail_update_preserves_hostile_notes` — hostile notes stored
  verbatim; `requests` table intact.
- `test_detail_route_rejects_non_integer_id` — Flask converter rejects
  non-integer id with 404.

**Verification:** `python3 -m pytest tests/ -v` → 16 passed in 0.11s
(10 deadline + 6 injection).

**Follow-ups (next):**
- Committed dev `secret_key = "dev"` and `debug=True` still ship.
  Move both to env-sourced config; disable debug in production.
- No authentication yet — audit-log question ("who changed this record
  and when") is still unanswerable.

---

## 2026-07-16 — Publish to GitHub

**Goal:** commit code to `https://github.com/iNileshW/Foi-Deadline-Tracker`.

**Files:**
- `.gitignore` (new — excludes `__pycache__/`, `*.pyc`, `.pytest_cache/`,
  `foi.db`, `*.db`, virtualenvs, `.env`)

**Actions:**
- `git init -b main`
- Remote `origin` set to the URL above.
- Verified remote was empty via `git ls-remote` before pushing — no
  divergence to reconcile.
- `foi.db` deliberately excluded from the repo: it is a runtime artefact
  recreated by `seed.py`, and the seed rows are sample PII-shaped data.
- `bank_holidays.json` **is** committed — it is a cache the app reads
  at runtime and lets tests run offline.
- Commit `01fb753` on `main`, 17 files, root commit.
- Pushed with `git push -u origin main`.

**Commit message summarises:** the deadline fix (with the Maundy
Thursday 2026-04-02 → 2026-05-05 correction), the SQL-injection
rewrite across all four query sites, and the 16-test pytest suite.

---

## 2026-07-16 — Move secret key and debug mode out of source

**Goal:** fix the secret_key and debug mode next.

**Files:**
- `app.py` (secret-loading helper, env-sourced debug/port/DB)
- `tests/conftest.py` (new — sets dev flag before app import)
- `tests/test_config.py` (new — 6 tests)
- `.env.example` (new)
- `README.md` (env vars documented, test invocation added)
- `CLAUDE.md` (defect list re-scored: three items now closed)

**Rationale:** `secret_key = "dev"` and `debug=True` were both hardcoded
in the inherited `app.py`. A dev secret in source means anyone with
repo read access can forge sessions; `debug=True` exposes the Werkzeug
console (RCE if reachable). ICO audit around access control cannot be
passed while either of these ships.

**Design choices:**
- `FOI_SECRET_KEY` is the *only* accepted way to configure the secret
  in production. `_load_secret_key()` raises `RuntimeError` on import
  if it is missing, so the app cannot silently degrade.
- The dev override is intentionally noisy: `FOI_ALLOW_INSECURE_DEV_SECRET=1`
  (exact string `"1"`, not `true` / `yes`). Only when this is set and
  `FOI_SECRET_KEY` is unset do we generate an ephemeral secret via
  `secrets.token_hex(32)`. Sessions do not survive process restart —
  by design, so developers feel the pain and set a real key.
- Debug flag: `FLASK_DEBUG=1` opt-in. Default off. Port and DB path
  also env-driven (`PORT`, `FOI_DB`).
- Existing tests import `app` module → the new import-time check would
  break them. Fixed with `tests/conftest.py`, which is loaded by pytest
  before any test module and sets the dev flag.

**Test coverage (`tests/test_config.py`):**
- `test_secret_key_from_env` — happy path.
- `test_dev_fallback_is_random_and_non_empty` — two calls return
  different values, each ≥32 chars, never the literal `"dev"`.
- `test_missing_secret_raises` — both env vars unset → `RuntimeError`
  whose message mentions `FOI_SECRET_KEY`.
- `test_dev_flag_other_value_does_not_bypass` — the string `"true"`
  does *not* enable the fallback. Only `"1"`.
- `test_app_import_fails_without_secret` — spawns a fresh
  `python -c "import app"` with a scrubbed env. This is the true
  production regression guard, and it can't be done via monkeypatch
  because `app` is already imported in the current test process.
- `test_debug_mode_defaults_off` — `app.debug is False` on the
  constructed Flask instance.

**Verification:** `python3 -m pytest tests/ -v` → 22 passed in 0.24s
(10 deadline + 6 injection + 6 config).

**Follow-ups (next):**
- Authentication + per-user accounts (two directorates joining).
- Audit log of record changes (`who`, `when`, `what`).
- Kill the destructive `seed.py` (it deletes `foi.db` unconditionally).
- Pin dependencies in `requirements.txt`.

---

## 2026-07-16 — Push config-hardening commit to GitHub

**Goal:** commit changes to repo.

**Files pushed:**
- 4 modified: `AI_Log.md`, `CLAUDE.md`, `README.md`, `app.py`
- 3 new: `.env.example`, `tests/conftest.py`, `tests/test_config.py`

**Commit:** `780a009` on `main`, fast-forward from `01fb753`.
**Push:** `git push origin main` → `01fb753..780a009  main -> main`.

---

## 2026-07-16 — Add session authentication and CSRF protection

**Goal:** add authentication next.

**Files:**
- `users.py` (new — `User` dataclass, password hashing, `authenticate`)
- `auth.py` (new — `login_required`, session helpers, CSRF)
- `app.py` (login/logout routes; `@login_required` on all existing
  routes; CSRF `before_request`; hardened session cookies)
- `create_user.py` (new — CLI to add users, password read from stdin)
- `seed.py` (calls `init_users_table`; no seeded users)
- `templates/base.html` (top-bar user + sign-out button)
- `templates/login.html` (new)
- `templates/new.html`, `templates/detail.html` (hidden CSRF field)
- `tests/test_sql_injection.py` (fixture now creates a logged-in
  session and adds `_csrf` to POST bodies)
- `tests/test_auth.py` (new — 15 tests)
- `README.md`, `CLAUDE.md` updated

**Rationale:** Two directorates joining means multi-team, real users,
and personal data. The ICO auditor will ask *who* accessed a record —
that question is unanswerable without identities. Auth is the
prerequisite for the audit log that comes next.

**Design choices:**
- Handrolled session auth on top of Flask's signed cookie session,
  no `flask-login` / `flask-wtf` dependencies. Fewer moving parts;
  no new install steps for the hackathon environment.
- Password hashing via `werkzeug.security.generate_password_hash`
  (already in the Flask dep tree). PBKDF2 by default; upgrade-in-place
  possible without a schema change because Werkzeug encodes the
  algorithm in the stored string.
- Password minimum length: 12 characters. Enforced in `create_user`,
  covered by a test.
- CSRF: per-session token in `session["csrf_token"]`, submitted as
  hidden `_csrf` form field, verified in `before_request` for all
  mutating verbs (including `/login` and `/logout`). Constant-time
  compare via `secrets.compare_digest`.
- Session cookie hardening: `HTTPOnly` always on, `SameSite=Lax`,
  `Secure` behind the `FOI_SECURE_COOKIES=1` env var so production
  can opt in without breaking `http://localhost` dev.
- Session rotation on login (`session.clear()` before setting
  `user_id`) to defeat session-fixation attacks.
- `?next=` open-redirect guard: only relative URLs starting with `/`
  are honoured; anything else falls back to `/`.
- Login failure returns HTTP 401 with a generic "Invalid email or
  password." message — no distinction between "unknown email",
  "wrong password", or "account disabled". Prevents user enumeration.
- No RBAC yet. Role and team live on `users` but no route consults
  them. Flagged as follow-up in CLAUDE.md.

**Test coverage (`tests/test_auth.py`, 15 tests):**
- Three unauthenticated routes redirect to `/login`.
- Wrong password → 401; unknown email → 401 (same status; enumeration
  guard).
- Successful login → 302; protected route now returns 200.
- Logout clears session; protected route redirects afterwards.
- CSRF: POST without token → 400; POST with wrong token → 400.
- Password not stored plaintext; stored hash starts with a known
  algorithm prefix.
- Disabled user (via `disabled_at` timestamp) cannot log in.
- `?next=https://evil.example.com/...` is ignored; redirect stays
  on-site.
- `create_user` refuses passwords shorter than 12 chars and unknown
  roles.
- Session id is rotated on login (pre-login session keys wiped).

**Existing tests updated:** `tests/test_sql_injection.py` fixture now
initialises the `users` table, opens a `session_transaction`, sets
`user_id` and a known `csrf_token`, and each POST test includes the
matching `_csrf` field. No behavioural regressions; all six original
injection tests still pass.

**Verification:** `python3 -m pytest tests/` → 37 passed, no warnings
(10 deadline + 6 injection + 6 config + 15 auth).

**Deprecation cleanup:** `users.py` uses `datetime.now(timezone.utc)`
instead of `datetime.utcnow()` to silence a Python 3.13
DeprecationWarning.

**Follow-ups (next):**
- Audit log: `record_changes(user_id, request_id, before, after,
  timestamp)`. Populate on POST /new and POST /request/<id>.
- RBAC: gate destructive edits or admin-only routes on `role`.
- Team-based data separation: add `team` to `requests`, filter
  index/detail queries by `current_user.team` for non-admins.
- Rate limiting / lockout on `/login`.
- Kill the destructive `seed.py`.

---

## 2026-07-16 — Hotfix: auto-create users table on legacy databases

**Goal:** browser reported HTTP 500 on POST /login.

**Symptom:** `sqlite3.OperationalError: no such table: users`.

**Root cause:** the existing `foi.db` in the working tree was
pre-auth — created before the users table existed. `seed.py` now
creates the table, but users who did not re-seed (correct: seed is
destructive of `requests`) still had the old schema. The auth code
paths blew up on the first `SELECT ... FROM users` in `authenticate`.

**Fix:** call `init_users_table(conn)` inside `app.get_db()` on every
connection. It's a `CREATE TABLE IF NOT EXISTS`, so it's idempotent
and cheap. Pre-auth databases pick up the users table transparently
the first time they hit any DB-backed route; already-migrated
databases are unaffected.

**Files:**
- `app.py` (`get_db` now calls `init_users_table`)

**Verification:**
- Full test suite still green: 37/37.
- Live reproduction with a fresh `foi.db` lacking the users table:
  - GET `/` → 302 to `/login`.
  - GET `/login` → 200, CSRF token issued.
  - POST `/login` (unknown user) → 401 (was 500).
  - The `users` table now exists in the database after the POST.
- Seeded `admin@dft.gov.uk` (role=admin, team=central) manually via
  `python3 -c "…create_user…"` to give the user a working local login.
  In production, `create_user.py EMAIL ROLE TEAM` is the intended path.

**Note on the earlier 500 during verification:** a Werkzeug dev server
from a previous run was still holding port 5002 after `kill` in an
earlier bash invocation. A fresh `fuser -k 5002/tcp` cleared it and
subsequent runs behaved correctly.

---

## 2026-07-16 — Push auth + hotfix to GitHub

**Goal:** log changes done with why in AI_Log.md & commit.

**Commit:** `3671641` on `main`, fast-forward from `780a009`. 14 files
changed, 747 insertions, 19 deletions.

**Push:** `git push origin main` → `780a009..3671641  main -> main`.

**Scope in one commit:** auth introduction (`auth.py`, `users.py`,
`create_user.py`, `login.html`, all POST forms carry `_csrf`),
`@login_required` on the three business routes, `before_request` CSRF
guard, session cookie hardening, tests (auth + updated injection),
plus the `get_db()` idempotent-schema hotfix. Bundled because the
hotfix without the schema change would still break; the auth changes
without the hotfix would break for anyone running against the
inherited `foi.db`.

---

## 2026-07-16 — Add append-only audit trail

**Goal:** next priority chosen as audit log (ICO auditor's direct
question: "who has accessed this requester's record?").

**Files:**
- `audit.py` (new — `init_audit_table`, `record_event`, `list_events`)
- `auth.py` (new `admin_required` decorator, keeps DB indirection)
- `app.py` (audit-writes on `/login` success + failure, `/logout`,
  `/new`, `/request/<id>` POST; new admin-only `/audit` route;
  `get_db()` now also idempotently creates the audit table)
- `templates/audit.html` (new — 200-row viewer with before/after JSON)
- `templates/base.html` (nav shows "Audit" link for admins only)
- `seed.py` (calls `init_audit_table`)
- `tests/test_audit.py` (new — 13 tests)
- `CLAUDE.md` re-scored: audit log closed; RBAC now partial.

**Rationale:** The Freedom of Information Act, UK GDPR, and the ICO
audit brief all converge on one question — *who* did *what*, *when*.
Without a change trail, the department cannot answer that question
for any record in the tracker. Authentication alone tells you who is
signed in *now*; the audit table tells you who was signed in when the
status flipped, when a record was created, when an unknown email
tried to log in ten times in a minute.

**Design choices:**
- Append-only from the app's perspective. The application code has
  no UPDATE or DELETE against `audit_events`. Retention/rotation is
  a DBA / backup concern.
- Actor identity denormalised: `actor_id` **and** `actor_email` are
  both stored. Emails survive user deletion so the auditor can still
  read "alice@dft.gov.uk did X" a year after Alice left. `actor_id`
  is nullable for pre-auth events (failed logins).
- Before/after snapshots stored as JSON strings. Human-readable in
  the admin viewer; queryable enough to diff without a specialised
  tool. `sort_keys=True` for stable ordering.
- Login failures record the *attempted* email so brute-force is
  visible in the trail. Passwords are never touched by
  `record_event`; a dedicated test proves the attempted password is
  nowhere in the row.
- User-Agent truncated to 255 chars (log-poisoning defence).
- Two indexes: `(target_type, target_id)` for "show me everything
  that touched this request" and `(actor_id, occurred_at)` for
  "show me everything Alice did last week".
- `admin_required(load_user)` follows the same DB-injection pattern
  as `current_user()` — `auth.py` stays free of a direct DB import.
- The audit viewer sits at `/audit`, admin-only, 200-row hard cap.
  Filter by `?target_type=request&target_id=42`.

**Schema:**
```
audit_events(
  id, occurred_at, actor_id, actor_email, action,
  target_type, target_id, before_json, after_json, ip, user_agent
)
```
Actions: `login.success`, `login.failure`, `logout`,
`request.create`, `request.update`. `request.view` is reserved.

**Test coverage (13 tests):**
- `login.success` writes actor_id + email + ip.
- `login.failure` writes NULL actor_id and the attempted email.
- Failed-login password is never persisted anywhere in the row
  (search across every column).
- `logout` writes actor identity.
- `request.create` writes an `after` JSON with the seeded fields;
  `before` is NULL.
- `request.update` writes both `before` and `after`; the values
  match the SELECT before UPDATE and the SELECT after UPDATE.
- `/audit` returns 403 for a logged-in caseworker.
- `/audit` returns 200 for an admin and includes at least one
  seeded event.
- `/audit` redirects anonymous callers to `/login`.
- Both audit indexes exist in the schema.
- `record_event` refuses unknown action names.
- Overly long User-Agent is truncated to 255 chars.
- `list_events(target_type, target_id)` filter returns only the
  matching rows.

**Verification:** `python3 -m pytest tests/` → 50 passed
(10 deadline + 6 injection + 6 config + 15 auth + 13 audit).

**Live smoke:** restarted the running app, logged in as
`admin@dft.gov.uk`, `GET /audit` → HTTP 200 with the login events
visible. Non-admin session (caseworker) receives 403.

**Follow-ups (next):**
- RBAC: gate `POST /new`, `POST /request/<id>` where write access
  should be scoped (currently any authenticated user can edit any
  request).
- Team-based data separation on `requests`.
- Backups + a proven restore drill (recoverability axis is still
  untouched).
- Rate limit `/login`; the trail records brute-force but nothing
  currently *slows* it down.

---

## 2026-07-16 — Backups with SQLite online API + proven restore drill

**Goal:** backups and proven restore next.

**Files:**
- `backup.py` (new — CLI + `backup_db` library function)
- `restore.py` (new — CLI + `restore_db` + `verify_backup`)
- `tests/test_backup.py` (new — 10 tests including a full round-trip)
- `.gitignore` (adds `backups/`, `*.pre-restore-*`, `*.restore-tmp`)
- `README.md` (backup + restore runbook + cron example)
- `CLAUDE.md` (defect list re-scored; recoverability now covered)

**Rationale:** The brief's fourth ICO audit axis is recoverability,
and its concrete probe is Q4 — "Gary's machine dies on a Wednesday.
Walk through the recovery, step by step, with the current setup and
with yours." The inherited answer is "a USB stick, on Fridays,
usually". The new answer is: hourly online-backup snapshots with
manifests, a restore that refuses to overwrite with a broken file,
a pre-restore safety copy so a bad restore is reversible, and a test
suite that runs the whole drill on every push.

**Design choices:**
- **SQLite online-backup API** (`conn.backup(target)`), not a file
  copy. A raw copy of `foi.db` during a write can produce a torn
  file. The online API pages through the source under a shared lock
  and yields a consistent snapshot even under concurrent writes.
  A dedicated test opens a live connection to the source while a
  backup runs, then reads the snapshot, to lock this behaviour in.
- **Manifest beside every snapshot**. `foi-<ts>.manifest.json` holds
  `created_at`, `source_path`, `backup_path`, `sha256`, `size_bytes`
  and per-table row counts. The auditor sees at a glance that the
  backup covered `requests`, `users`, `audit_events`, and the sha256
  proves nothing has been tampered with post-hoc.
- **Microsecond-resolution timestamps** in filenames
  (`%Y%m%dT%H%M%S%fZ`) so back-to-back calls never collide. Sortable
  by name; matches `ls -t` order.
- **Keep-N pruning** driven by filename sort, default 14. Zero
  disables. Manifest deleted together with its `.db`.
- **`restore.py` verifies the backup before touching prod.** Refuses
  to proceed if the file cannot open or lacks a `requests` table.
  Then, if the target already exists, it is copied aside as
  `foi.db.pre-restore-<UTC>` — botched restore is undoable.
  The final write goes through a `.restore-tmp` + atomic rename
  so a running app never reads a half-copied file.
- **Off-machine transport is out of scope.** Documented explicitly:
  point `rsync` / `aws s3 sync` at `backups/`. Baking a specific
  transport into the tool would fight whatever DfT's approved
  method is.
- `_now` seam on `backup_db` lets tests use deterministic labels
  instead of `time.sleep(1)` for prune tests.

**Test coverage (`tests/test_backup.py`, 10 tests):**
- Snapshot + manifest present, sha256 length correct, table counts
  include `requests`, `users`, `audit_events`.
- Prune keeps only N. Five backups with `keep=3` leaves three;
  manifests pruned in lockstep.
- Missing source → `FileNotFoundError`.
- **Round-trip drill:** seed → backup → mutate (add row) → restore
  → assert row count returns to seeded value and the safety copy
  holds the mutation.
- Backup missing `requests` table → `ValueError`; existing prod DB
  untouched by size.
- Pre-restore safety copy exists and contains the pre-restore state.
- Online-backup API works with a source connection held open
  concurrently.
- `verify_backup` on a missing file raises.
- Restore to a target that does not yet exist returns `safety=None`
  and creates the file.
- Manifest sha256 matches an independent hash of the snapshot file.

**Verification:**
- `python3 -m pytest tests/` → 60 passed
  (10 deadline + 6 injection + 6 config + 15 auth + 13 audit + 10 backup).
- **Live drill against real `foi.db`:**
  - `python3 backup.py foi.db backups 5` produced
    `foi-20260716T222958532582Z.db` (32 KB) with matching manifest
    (sha256 present, `requests=13`, `users=1`, `audit_events=1`).
  - Inserted a `FOI-DRILL` row into live DB — count 13 → 14.
  - `python3 restore.py backups/foi-<ts>.db foi.db` — count 14 → 13,
    `FOI-DRILL` row gone, `foi.db.pre-restore-<ts>` safety copy
    exists on disk.

**Answer to brief Q4 (Gary's Wednesday):**
- Before: "we hope Gary's Friday USB copy is on Gary's other machine".
- After: hourly manifested snapshots in `backups/` synced off-host
  by cron; the restore is one command with an automatic pre-restore
  safety copy; the drill is in CI so a broken restore path is caught
  before Gary needs it.

**Follow-ups (next):**
- Rate limit `/login`.
- Team-based data separation on `requests`.
- CI pipeline (tests + security scan + deploy) — brief's fifth
  direction. Now warranted; 60 tests worth of guardrails.
- UK GDPR retention policy on requester PII (data-protection axis
  is only half-covered — audit log exists, retention rule does not).

---

## 2026-07-16 — Add GitHub Actions CI pipeline

**Goal:** set up the CI pipeline next.

**Files:**
- `.github/workflows/ci.yml` (new — three jobs)
- `backup.py` (bandit `# nosec B608` on the `SELECT COUNT(*) FROM
  "<table>"` in `_table_counts` — table name is from sqlite_master,
  not user input)
- `deadlines.py` (bandit `# nosec B310` on `urllib.request.urlopen`
  — URL is a hardcoded https constant, not user input)
- `README.md` (CI badge, local scan commands, CI job overview)
- `CLAUDE.md` (defect list — CI item closed)

**Rationale:** 60 tests exist locally. Without CI, they run when
someone remembers to run them. With CI, they run on every push and
pull request and no unreviewed regression can reach `main`. The brief
lists CI as its own direction — this operationalises the guardrails
built in the previous six changes.

**Design choices:**
- **Three jobs, no deploy.** Test, security, package. Deploy is
  deliberately not automated because there is no shared production
  target — automating a broken deploy path is worse than not
  automating one. Package uploads a versioned tarball on merges to
  `main` so the artifact story is at least ready.
- **Python matrix 3.11 / 3.12 / 3.13.** Cheap, catches version-
  sensitive bugs (like the `datetime.utcnow` deprecation caught
  earlier). `fail-fast: false` so a single-version failure does not
  hide the others.
- **`concurrency` block** cancels in-progress runs for the same ref
  to save minutes on force-pushes.
- **Bandit** in SAST mode, `-ll` reports Low severity and above,
  Low confidence and above. Excludes `tests/` (fixtures contain
  deliberate hostile inputs), `templates/`, `.github/`, `backups/`.
  Two findings triaged as false positives and annotated `# nosec`
  in-source with a reason:
    - `backup.py:_table_counts` uses `sqlite_master.name` in an
      f-string COUNT query. Identifiers cannot be parameter-bound;
      the value never touches user input.
    - `deadlines.py:load_bank_holidays` calls `urllib.request.urlopen`
      on a hardcoded https URL. Not user-controlled.
- **pip-audit** runs `--strict` against both `requirements.txt` and
  `requirements-dev.txt`. `--strict` fails the job on any known
  vulnerable dependency, not just when audit itself errors.
- **`actions/setup-python@v5` with `cache: pip`** — cheap install-
  time optimisation across the matrix.

**Verification (local dry run):**
- `bandit -r . -x ./tests,./templates,./.github,./backups -ll` — 0
  issues after the two `# nosec` annotations, 2 suppressed with
  reasons in the source.
- `pip-audit --strict -r requirements.txt` — no vulnerabilities.
- `pip-audit --strict -r requirements-dev.txt` — no vulnerabilities.
- `python3 -m pytest tests/` — 60 passed.

**Verification (remote):** to be observed after the push in the
"Actions" tab of the GitHub repo.

**Follow-ups (next):**
- Container (`Dockerfile` + `docker-compose.yml`). Now that CI can
  build an image, doing so becomes a real deploy story.
- Pin `flask` (and any transitive deps we care about) in
  `requirements.txt` so pip-audit results are reproducible.
- Rate-limit `/login`; team-scoping; UK GDPR retention.

---

## 2026-07-16 — Containerise: Dockerfile + compose + healthcheck

**Goal:** container next.

**Files:**
- `Dockerfile` (new — python:3.13-slim, gunicorn, non-root UID 10001)
- `docker-compose.yml` (new — one service, named volume for data)
- `.dockerignore` (new — excludes .git, tests, foi.db, backups, docs)
- `app.py` (new `/healthz` route)
- `requirements.txt` (adds `gunicorn`)
- `seed.py` (respects `FOI_DB` env var — previously hardcoded to
  `foi.db`; would silently seed the wrong path inside the container)
- `.github/workflows/ci.yml` (new `docker` job — builds the image on
  every push and PR, with gha-cache)
- `tests/test_healthz.py` (new — 3 tests)
- `README.md` + `CLAUDE.md` updated

**Rationale:** The Flask dev server carries a Werkzeug warning for a
reason. Under any real load it's single-threaded and the debugger
console is one misconfiguration away from RCE. A container-based
deploy replaces "Gary's desktop" with something an ops team can
schedule, restart, and probe.

**Design choices:**
- **Base image:** `python:3.13-slim`. Adds `curl` only (for the
  in-container healthcheck), no compilers, no build tools.
- **Non-root user:** fixed UID/GID 10001 so bind-mounted volumes
  behave predictably on hosts that share the range.
- **Gunicorn** (not the Flask dev server), `--workers 2` by default,
  tunable with `WEB_CONCURRENCY`. Access + error logs to stdout so
  a log driver can pick them up.
- **Volume mount at `/data`:** the SQLite file lives there so it
  survives container re-creates. `FOI_DB=/data/foi.db` set in the
  image.
- **`/healthz` route:** opens the DB and probes every schema-critical
  table (`requests`, `users`, `audit_events`). Returns
  `{"status": "ok"}` 200 when the schema is present, 503 otherwise.
  Wired into `HEALTHCHECK` and the compose `healthcheck:` block.
  Public, no auth — orchestrators must be able to probe.
- **`seed.py` bug fix:** previously wrote to a relative `foi.db`.
  Under the container, that's `/app/foi.db`, not `/data/foi.db`.
  Now reads `FOI_DB` — the smoke test caught this before push.
- **CI docker job:** `docker/setup-buildx-action` + `build-push-action`
  with GHA layer cache. Build-only, no push. Catches Dockerfile
  regressions on every PR.
- **`.dockerignore`** excludes tests, docs, `.git`, `foi.db`, backups.
  Image stays small; secrets and DB state never accidentally ship.

**Verification (local):**
- `docker build -t foi-tracker:local .` — builds clean.
- `docker run` with `FOI_ALLOW_INSECURE_DEV_SECRET=1` and a named
  volume: gunicorn starts, listens on 8080, 2 workers boot.
- `GET /healthz` on an empty volume → 503 (schema missing). Correct.
- `docker exec … python seed.py` writes `/data/foi.db` (env-driven
  path); `/healthz` → 200 with `{"status":"ok"}`.
- `docker exec … python create_user.py admin@dft.gov.uk admin central`
  creates an admin.
- Full login flow through the containerised app: POST /login → 302,
  authed GET / → 200, 12 seeded rows rendered.
- Container + volume cleaned up.
- `python3 -m pytest tests/` → 63 passed (10 deadline + 6 injection +
  6 config + 15 auth + 13 audit + 10 backup + 3 healthz).

**Note on the podman HEALTHCHECK warning:** the local host has podman
in Docker-compat mode. Podman's default OCI format ignores the
Dockerfile `HEALTHCHECK` instruction (warning: *HEALTHCHECK is not
supported for OCI image format*). The compose-level `healthcheck:`
block still fires under podman. Under real Docker Engine both work.

**Follow-ups (next):**
- Pin `requirements.txt`.
- Rate-limit `/login`.
- Team-based data separation on requests.

---
