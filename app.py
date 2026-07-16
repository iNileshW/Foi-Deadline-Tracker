# FOI Deadline Tracker
# Tracks Freedom of Information requests and their statutory deadlines.

import os
import secrets
import sqlite3
from datetime import date, datetime, timezone

from flask import (
    Flask,
    abort,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from audit import list_events, record_event
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
from ratelimit import is_locked, seconds_until_unlock
from retention import redact_request
from schema import init_all
from users import authenticate, get_user_by_id


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
    # and columns without a destructive re-seed.
    init_all(conn)
    return conn


def _team_scope_where(user, table_alias: str = ""):
    """Return an (SQL fragment, params) tuple restricting a query to
    the caller's team plus legacy-unassigned rows. Admins see all."""
    col = f"{table_alias}.team" if table_alias else "team"
    if user is None or user.role == "admin":
        return "", []
    return f" AND ({col} = ? OR {col} = '')", [user.team]


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
        ctx = _request_context()
        norm_email = email.lower().strip() or None
        ip = ctx["ip"]

        if is_locked(db, email=norm_email, ip=ip):
            retry = seconds_until_unlock(db, email=norm_email, ip=ip)
            record_event(
                db,
                "login.blocked",
                actor_email=norm_email,
                **ctx,
            )
            flash("Too many failed attempts. Try again later.", "error")
            resp = make_response(render_template("login.html"), 429)
            resp.headers["Retry-After"] = str(retry)
            return resp

        user = authenticate(db, email, password)
        if user is None:
            record_event(
                db,
                "login.failure",
                actor_email=norm_email,
                **ctx,
            )
            flash("Invalid email or password.", "error")
            return render_template("login.html"), 401
        login_user(user.id)
        record_event(
            db,
            "login.success",
            actor_id=user.id,
            actor_email=user.email,
            **ctx,
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
    user = current_user(_load_user)
    scope_sql, scope_params = _team_scope_where(user)
    q = request.args.get("q", "")
    # `scope_sql` is a literal fragment built in _team_scope_where;
    # values are parameter-bound.
    base = "SELECT * FROM requests WHERE (subject LIKE ? OR requester LIKE ?)"  # nosec B608
    base_all = "SELECT * FROM requests WHERE 1=1"  # nosec B608
    order = " ORDER BY deadline"
    if q:
        like = f"%{q}%"
        rows = db.execute(base + scope_sql + order, (like, like, *scope_params)).fetchall()
    else:
        rows = db.execute(base_all + scope_sql + order, scope_params).fetchall()

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
        user = current_user(_load_user)
        team = user.team if user else ""
        cur = db.execute(
            "INSERT INTO requests "
            "(ref, requester, subject, received, deadline, status, team) "
            "VALUES (?, ?, ?, ?, ?, 'Received', ?)",
            (ref, requester, subject, received, deadline.isoformat(), team),
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
            "team": team,
        }
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
    user = current_user(_load_user)
    scope_sql, scope_params = _team_scope_where(user)

    # `scope_sql` is a literal fragment from _team_scope_where.
    row = db.execute(
        "SELECT * FROM requests WHERE id = ?" + scope_sql,  # nosec B608
        (req_id, *scope_params),
    ).fetchone()
    # Out-of-team requests 404 rather than 403 — don't confirm the row exists.
    if row is None:
        abort(404)

    if request.method == "POST":
        status = request.form["status"]
        notes = request.form["notes"]

        before_row = row
        # Stamp responded_at on the transition to Responded. Do not
        # overwrite on subsequent Responded → Responded updates.
        transitioning = (
            status == "Responded" and before_row["status"] != "Responded"
        )
        if transitioning:
            responded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            db.execute(
                "UPDATE requests SET status = ?, notes = ?, responded_at = ? WHERE id = ?",
                (status, notes, responded_at, req_id),
            )
        else:
            db.execute(
                "UPDATE requests SET status = ?, notes = ? WHERE id = ?",
                (status, notes, req_id),
            )
        db.commit()

        after_row = db.execute(
            "SELECT * FROM requests WHERE id = ?", (req_id,)
        ).fetchone()

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

    today = date.today().isoformat()
    return render_template("detail.html", r=row, statuses=STATUSES, today=today)


@app.route("/healthz")
def healthz():
    """Liveness + readiness probe.

    Verifies the DB opens and the schema-critical tables exist. If the
    check succeeds the container is healthy; if it fails, Docker's
    HEALTHCHECK marks the container unhealthy so the orchestrator can
    restart or route around it.
    """
    try:
        db = get_db()
        db.execute("SELECT 1 FROM requests LIMIT 1")
        db.execute("SELECT 1 FROM users LIMIT 1")
        db.execute("SELECT 1 FROM audit_events LIMIT 1")
    except Exception:
        return {"status": "unhealthy"}, 503
    return {"status": "ok"}, 200


@app.route("/request/<int:req_id>/erase-pii", methods=["POST"])
@admin_required(_load_user)
def erase_pii(req_id):
    """DSAR / right-to-erasure endpoint. Admin-only.

    Redacts the requester name and free-text notes. Case metadata
    (ref, subject, dates, status, deadline, team) is retained so the
    FOI statistical return survives the redaction.
    """
    db = get_db()
    ctx = _request_context()
    reason = request.form.get("reason", "").strip() or "admin request"
    user = current_user(_load_user)
    ok = redact_request(
        db,
        req_id,
        actor=user,
        reason=reason,
        ip=ctx["ip"],
        user_agent=ctx["user_agent"],
    )
    if not ok:
        # Row missing or already redacted — either way, no state change.
        row = db.execute(
            "SELECT id FROM requests WHERE id = ?", (req_id,)
        ).fetchone()
        if row is None:
            abort(404)
        flash("Request PII was already redacted.", "error")
    else:
        flash("Requester PII redacted.", "success")
    return redirect(f"/request/{req_id}")


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
