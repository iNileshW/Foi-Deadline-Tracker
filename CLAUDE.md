# FOI Deadline Tracker — CLAUDE.md

Flask CRUD app tracking Freedom of Information requests for DfT central FOI team. Inherited prototype from hackathon Scenario 3. Goal: make production-grade before autumn ICO audit.

## Context

- 6 caseworkers use daily. Two more directorates joining → multi-team, personal data (requester names/addresses under UK GDPR).
- ICO audit incoming autumn 2026. Scope: deadline accuracy, data protection, access control, recoverability.
- One statutory FOIA breach already occurred: request received Thursday before Easter, deadline calc ignored bank holidays.

## Definition of Done

Pass an ICO auditor asking about: **deadline accuracy, data protection, access control, recoverability**. Prioritise the gap that matters most; defend the call.

## Known Defects (as inherited)

- `deadlines.py:calculate_deadline` — skips Sat/Sun only. Bank holidays not handled. Root cause of statutory breach. **Highest-value fix.**
- `app.py:32-35, 54-58, 72-74, 78` — SQL built by f-string interpolation of user input. Injection open in search, insert, update, detail lookup.
- `app.py:13` — `secret_key = "dev"`. Committed dev secret.
- `app.py:84` — `debug=True`. Werkzeug debugger + PIN over network.
- No authentication. No RBAC. No per-user identity.
- No audit log. Cannot answer "who changed this record and when".
- `seed.py:10-11` — deletes `foi.db` unconditionally on run. Destructive.
- `foi.db` lives next to code. Backup = Gary's USB stick, Fridays, "usually".
- Zero tests. Zero CI. Zero container. Zero secret management.
- `requirements.txt` — unpinned `flask` only.

## Architecture

- `app.py` — Flask app, port 5002, routes: `/`, `/new`, `/request/<id>`.
- `deadlines.py` — `calculate_deadline(received: date) -> date`, 20 working days.
- `seed.py` — recreates `foi.db` with sample rows.
- `templates/` — `base.html`, `index.html`, `new.html`, `detail.html`.
- `foi.db` — SQLite, single table `requests(id, ref, requester, subject, received, deadline, status, notes)`.
- Statuses: `Received`, `In progress`, `Internal review`, `Responded`, `Overdue`.

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
