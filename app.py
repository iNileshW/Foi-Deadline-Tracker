# FOI Deadline Tracker
# Tracks Freedom of Information requests and their statutory deadlines.

import os
import secrets
import sqlite3
from datetime import date, datetime

from flask import Flask, redirect, render_template, request

from deadlines import calculate_deadline


def _load_secret_key() -> str:
    """Return a Flask session secret.

    Production: `FOI_SECRET_KEY` must be set. Generate one with
        python -c 'import secrets; print(secrets.token_hex(32))'
    Local development only: `FOI_ALLOW_INSECURE_DEV_SECRET=1` swaps in
    a per-process random secret. Sessions do not survive a restart.
    """
    secret = os.environ.get("FOI_SECRET_KEY")
    if secret:
        return secret
    if os.environ.get("FOI_ALLOW_INSECURE_DEV_SECRET") == "1":
        return secrets.token_hex(32)
    raise RuntimeError(
        "FOI_SECRET_KEY is required. "
        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'. "
        "For local development only, set FOI_ALLOW_INSECURE_DEV_SECRET=1."
    )


app = Flask(__name__)
app.secret_key = _load_secret_key()

DB = os.environ.get("FOI_DB", "foi.db")

STATUSES = ["Received", "In progress", "Internal review", "Responded", "Overdue"]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "")
    if q:
        like = f"%{q}%"
        rows = db.execute(
            "SELECT * FROM requests "
            "WHERE subject LIKE ? OR requester LIKE ? "
            "ORDER BY deadline",
            (like, like),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM requests ORDER BY deadline").fetchall()

    today = date.today().isoformat()
    return render_template("index.html", rows=rows, q=q, today=today)


@app.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "POST":
        ref = request.form["ref"]
        requester = request.form["requester"]
        subject = request.form["subject"]
        received = request.form["received"]

        deadline = calculate_deadline(datetime.strptime(received, "%Y-%m-%d").date())

        db = get_db()
        db.execute(
            "INSERT INTO requests (ref, requester, subject, received, deadline, status) "
            "VALUES (?, ?, ?, ?, ?, 'Received')",
            (ref, requester, subject, received, deadline.isoformat()),
        )
        db.commit()
        return redirect("/")

    return render_template("new.html", today=date.today().isoformat())


@app.route("/request/<int:req_id>", methods=["GET", "POST"])
def detail(req_id):
    db = get_db()

    if request.method == "POST":
        status = request.form["status"]
        notes = request.form["notes"]
        db.execute(
            "UPDATE requests SET status = ?, notes = ? WHERE id = ?",
            (status, notes, req_id),
        )
        db.commit()
        return redirect(f"/request/{req_id}")

    row = db.execute(
        "SELECT * FROM requests WHERE id = ?", (req_id,)
    ).fetchone()
    today = date.today().isoformat()
    return render_template("detail.html", r=row, statuses=STATUSES, today=today)


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5002"))
    app.run(debug=debug, port=port)
