"""Session-based authentication and CSRF protection.

`login_required` gates a view behind an authenticated session.
`current_user()` returns the logged-in User (or None) for the request.
CSRF: every mutating request must include a `_csrf` form field
matching the token in the session. Tokens are per-session.
"""

from __future__ import annotations

import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

_admin_load_user = None  # set by the app at startup, used by admin_required


def current_user(load_user):
    """Return the current User (cached on flask.g) or None.

    `load_user(user_id)` is injected by the app so this module has
    no direct DB dependency.
    """
    if "user" not in g:
        uid = session.get("user_id")
        g.user = load_user(uid) if uid is not None else None
    return g.user


def login_user(user_id: int) -> None:
    # Rotate session id on privilege change to defeat fixation.
    session.clear()
    session["user_id"] = int(user_id)
    session["csrf_token"] = secrets.token_urlsafe(32)


def logout_user() -> None:
    session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(load_user):
    """Return a decorator that gates a view on role == 'admin'.

    `load_user(user_id)` is injected by the app so this module stays
    free of a direct DB dependency.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            uid = session.get("user_id")
            if uid is None:
                return redirect(url_for("login", next=request.path))
            user = load_user(uid)
            if user is None or user.role != "admin":
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def get_csrf_token() -> str:
    tok = session.get("csrf_token")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf_token"] = tok
    return tok


def verify_csrf() -> None:
    """Abort 400 if the POSTed token is missing or does not match."""
    submitted = request.form.get("_csrf", "")
    expected = session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(submitted, expected):
        abort(400, description="CSRF token missing or invalid")
