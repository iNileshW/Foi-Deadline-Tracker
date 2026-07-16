# FOI Deadline Tracker

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
python seed.py       # creates foi.db with sample data (wipes existing data!)

# Production: set a real secret.
export FOI_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')

# Local development shortcut (ephemeral secret, sessions don't survive restart):
# export FOI_ALLOW_INSECURE_DEV_SECRET=1

python app.py
```

Then open http://localhost:5002

## Configuration

| Env var | Purpose | Default |
| --- | --- | --- |
| `FOI_SECRET_KEY` | Flask session secret. **Required** unless dev override set. | — |
| `FOI_ALLOW_INSECURE_DEV_SECRET` | If `1`, generate an ephemeral secret when `FOI_SECRET_KEY` is unset. Local dev only. | unset |
| `FLASK_DEBUG` | Set to `1` to enable Werkzeug debugger. Do not enable in production. | `0` |
| `FOI_DB` | Path to the SQLite database file. | `foi.db` |
| `PORT` | HTTP port. | `5002` |

See `.env.example`.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Notes

- Deadlines are 20 working days from receipt (weekends excluded).
- The search box was added quickly for the team — it matches subject
  or requester name.
- Everyone shares the same screen, no logins. It's internal so fine.
- Backups: Gary copies foi.db to a USB stick on Fridays, usually.
