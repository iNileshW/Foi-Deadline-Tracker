# FOI Deadline Tracker
# Tracks Freedom of Information requests and their statutory deadlines.

import sqlite3
from datetime import date, datetime

from flask import Flask, redirect, render_template, request

from deadlines import calculate_deadline

app = Flask(__name__)
app.secret_key = "dev"  # TODO: replace with env-sourced secret

DB = "foi.db"

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
    app.run(debug=True, port=5002)
