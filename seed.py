# Creates foi.db and loads some sample requests.
# Run once: python seed.py  (deletes any existing database!)

import os
import sqlite3
from datetime import date, timedelta

from deadlines import calculate_deadline
from schema import init_all

DB = os.environ.get("FOI_DB", "foi.db")

if os.path.exists(DB):
    os.remove(DB)

conn = sqlite3.connect(DB)
init_all(conn)

SAMPLE = [
    # (ref, requester, subject, days_ago, status, team)
    ("FOI-2026-0141", "J. Whitfield", "Pothole repair spend by borough, 2024-2026", 38, "Responded", "roads"),
    ("FOI-2026-0152", "Roadside Truths blog", "Smart motorway incident response times", 31, "Responded", "roads"),
    ("FOI-2026-0159", "M. Osei", "Rail electrification feasibility studies since 2020", 27, "Internal review", "rail"),
    ("FOI-2026-0163", "Kent Online", "Correspondence about the Lower Thames Crossing", 24, "In progress", "roads"),
    ("FOI-2026-0170", "S. Brar", "EV charging point grant applications rejected in 2025", 19, "In progress", "roads"),
    ("FOI-2026-0174", "Cycling UK", "Active travel budget reallocations", 16, "In progress", "central"),
    ("FOI-2026-0178", "P. Lindqvist", "Ministerial meetings with airline lobbyists", 12, "In progress", "central"),
    ("FOI-2026-0181", "Transport Action Group", "Bus service improvement plan funding formula", 9, "Received", "rail"),
    ("FOI-2026-0183", "A. Ncube", "Driving test backlog by test centre", 6, "Received", "central"),
    ("FOI-2026-0185", "The Herald", "Costs of the pavement parking consultation", 3, "Received", "central"),
    ("FOI-2026-0186", "R. Kaminski", "Departmental spend on taxis, 2025", 1, "Received", "central"),
    ("FOI-2026-0187", "L. Fortescue", "Bridge inspection reports for the A38", 0, "Received", "roads"),
]

for ref, requester, subject, days_ago, status, team in SAMPLE:
    received = date.today() - timedelta(days=days_ago)
    deadline = calculate_deadline(received)
    conn.execute(
        "INSERT INTO requests "
        "(ref, requester, subject, received, deadline, status, notes, team) "
        "VALUES (?, ?, ?, ?, ?, ?, '', ?)",
        (ref, requester, subject, received.isoformat(), deadline.isoformat(), status, team),
    )

conn.commit()
conn.close()
print(f"Seeded {DB} with {len(SAMPLE)} requests")
print("No users created. Add one with: python create_user.py EMAIL ROLE TEAM")
