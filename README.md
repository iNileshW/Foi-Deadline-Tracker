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
python app.py
```

Then open http://localhost:5002

## Notes

- Deadlines are 20 working days from receipt (weekends excluded).
- The search box was added quickly for the team — it matches subject
  or requester name.
- Everyone shares the same screen, no logins. It's internal so fine.
- Backups: Gary copies foi.db to a USB stick on Fridays, usually.
