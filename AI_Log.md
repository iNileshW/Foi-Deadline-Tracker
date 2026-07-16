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
