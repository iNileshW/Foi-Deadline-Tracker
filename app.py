# FOI Deadline Tracker
# Tracks Freedom of Information requests and their statutory deadlines.

import os
import secrets
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from audit import init_audit_table, list_events, record_event
from auth import (
    admin_required,
    current_user,
    get_csrf_token,
    login_required,
    login_user,
    logout_user,
    verify_csrf,
)
from deadlines import calculate_deadline
from users import authenticate, get_user_by_id, init_users_table


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
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FOI_SECURE_COOKIES", "0") == "1",
)

DB = os.environ.get("FOI_DB", "foi.db")

STATUSES = ["Received", "In progress", "Internal review", "Responded", "Overdue"]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # Idempotent schema init: pre-existing databases pick up new tables
    # without a destructive re-seed. `CREATE TABLE IF NOT EXISTS` is cheap.
    init_users_table(conn)
    init_audit_table(conn)
    return conn


def _load_user(user_id):
    if user_id is None:
        return None
    return get_user_by_id(get_db(), user_id)


def _row_to_dict(row):
    return dict(row) if row is not None else None


def _request_context():
    return {
        "ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
    }


@app.before_request
def _csrf_guard():
    # Verify CSRF on every state-changing request, including /login.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        verify_csrf()


@app.context_processor
def _template_context():
    return {
        "csrf_token": get_csrf_token,
        "current_user": current_user(_load_user),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        db = get_db()
        user = authenticate(db, email, password)
        if user is None:
            record_event(
                db,
                "login.failure",
                actor_email=email.lower().strip() or None,
                **_request_context(),
            )
            flash("Invalid email or password.", "error")
            return render_template("login.html"), 401
        login_user(user.id)
        record_event(
            db,
            "login.success",
            actor_id=user.id,
            actor_email=user.email,
            **_request_context(),
        )
        next_url = request.args.get("next") or url_for("index")
        if not next_url.startswith("/"):
            next_url = url_for("index")
        return redirect(next_url)
    get_csrf_token()
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    user = current_user(_load_user)
    if user is not None:
        record_event(
            get_db(),
            "logout",
            actor_id=user.id,
            actor_email=user.email,
            **_request_context(),
        )
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
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
@login_required
def new():
    if request.method == "POST":
        ref = request.form["ref"]
        requester = request.form["requester"]
        subject = request.form["subject"]
        received = request.form["received"]

        deadline = calculate_deadline(datetime.strptime(received, "%Y-%m-%d").date())

        db = get_db()
        cur = db.execute(
            "INSERT INTO requests (ref, requester, subject, received, deadline, status) "
            "VALUES (?, ?, ?, ?, ?, 'Received')",
            (ref, requester, subject, received, deadline.isoformat()),
        )
        db.commit()

        new_id = int(cur.lastrowid)
        after = {
            "id": new_id,
            "ref": ref,
            "requester": requester,
            "subject": subject,
            "received": received,
            "deadline": deadline.isoformat(),
            "status": "Received",
        }
        user = current_user(_load_user)
        record_event(
            db,
            "request.create",
            actor_id=user.id if user else None,
            actor_email=user.email if user else None,
            target_type="request",
            target_id=new_id,
            after=after,
            **_request_context(),
        )
        return redirect("/")

    return render_template("new.html", today=date.today().isoformat())


@app.route("/request/<int:req_id>", methods=["GET", "POST"])
@login_required
def detail(req_id):
    db = get_db()

    if request.method == "POST":
        status = request.form["status"]
        notes = request.form["notes"]

        before_row = db.execute(
            "SELECT * FROM requests WHERE id = ?", (req_id,)
        ).fetchone()
        if before_row is None:
            abort(404)

        db.execute(
            "UPDATE requests SET status = ?, notes = ? WHERE id = ?",
            (status, notes, req_id),
        )
        db.commit()

        after_row = db.execute(
            "SELECT * FROM requests WHERE id = ?", (req_id,)
        ).fetchone()

        user = current_user(_load_user)
        record_event(
            db,
            "request.update",
            actor_id=user.id if user else None,
            actor_email=user.email if user else None,
            target_type="request",
            target_id=req_id,
            before=_row_to_dict(before_row),
            after=_row_to_dict(after_row),
            **_request_context(),
        )
        return redirect(f"/request/{req_id}")

    row = db.execute(
        "SELECT * FROM requests WHERE id = ?", (req_id,)
    ).fetchone()
    today = date.today().isoformat()
    return render_template("detail.html", r=row, statuses=STATUSES, today=today)


@app.route("/audit")
@admin_required(_load_user)
def audit_view():
    db = get_db()
    target_type = request.args.get("target_type") or None
    target_id_raw = request.args.get("target_id")
    target_id = int(target_id_raw) if target_id_raw and target_id_raw.isdigit() else None
    events = list_events(db, limit=200, target_type=target_type, target_id=target_id)
    return render_template("audit.html", events=events)


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5002"))
    app.run(debug=debug, port=port)
