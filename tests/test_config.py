"""Tests for session-secret loading and debug-mode defaults."""

import subprocess
import sys
import textwrap

import pytest

import app as app_module


def test_secret_key_from_env(monkeypatch):
    monkeypatch.setenv("FOI_SECRET_KEY", "a" * 64)
    monkeypatch.delenv("FOI_ALLOW_INSECURE_DEV_SECRET", raising=False)
    assert app_module._load_secret_key() == "a" * 64


def test_dev_fallback_is_random_and_non_empty(monkeypatch):
    monkeypatch.delenv("FOI_SECRET_KEY", raising=False)
    monkeypatch.setenv("FOI_ALLOW_INSECURE_DEV_SECRET", "1")
    a = app_module._load_secret_key()
    b = app_module._load_secret_key()
    assert a and b
    assert a != b  # random each call
    assert len(a) >= 32
    assert a != "dev"


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("FOI_SECRET_KEY", raising=False)
    monkeypatch.delenv("FOI_ALLOW_INSECURE_DEV_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="FOI_SECRET_KEY"):
        app_module._load_secret_key()


def test_dev_flag_other_value_does_not_bypass(monkeypatch):
    """Only the exact string '1' enables the dev fallback."""
    monkeypatch.delenv("FOI_SECRET_KEY", raising=False)
    monkeypatch.setenv("FOI_ALLOW_INSECURE_DEV_SECRET", "true")
    with pytest.raises(RuntimeError):
        app_module._load_secret_key()


def test_app_import_fails_without_secret():
    """A fresh interpreter with neither env var set must refuse to start
    the app. This is the production safety net."""
    script = textwrap.dedent(
        """
        import os, sys
        os.environ.pop("FOI_SECRET_KEY", None)
        os.environ.pop("FOI_ALLOW_INSECURE_DEV_SECRET", None)
        try:
            import app  # noqa: F401
        except RuntimeError as e:
            assert "FOI_SECRET_KEY" in str(e)
            sys.exit(0)
        sys.exit(1)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(app_module.__file__).parent),
    )
    assert result.returncode == 0, result.stderr


def test_debug_mode_defaults_off():
    """The Flask app object itself must not carry debug=True by default.

    `app.debug` reflects the value passed to app.run(); Flask also
    honours the FLASK_DEBUG env var when the reloader inspects it, but
    the constructed app should be clean.
    """
    assert app_module.app.debug is False
