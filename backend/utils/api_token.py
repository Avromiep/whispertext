"""Local API token — a shared secret that gates the backend so only the
WhisperText app (which can read the token file) can call it, not a random web
page or another process that merely knows the port.

A fresh token is generated each launch and written to a single small file in the
app data dir (overwritten in place — it never accumulates). The Electron app
reads that file and sends the token on every request; the backend checks it.
This blocks the realistic threat (a website POSTing to 127.0.0.1) but, on a
single-user machine, can't stop a program running AS the user from reading the
file — that's an OS-level limit, not something a local server can close.
"""
from __future__ import annotations

import secrets

from backend.config import APP_DIR
from backend.utils.logger import get_logger

log = get_logger(__name__)

TOKEN_FILE = APP_DIR / "api-token"
_token: str | None = None


def ensure_token() -> str:
    """Generate a fresh token and write it to the token file. Called once at
    startup, before the server accepts requests."""
    global _token
    _token = secrets.token_urlsafe(32)
    try:
        TOKEN_FILE.write_text(_token, encoding="utf-8")
    except Exception as exc:
        log.warning("Could not write API token file: %s", exc)
    return _token


def get_token() -> str:
    """The current token (falls back to reading the file if not in memory)."""
    global _token
    if _token is None:
        try:
            _token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            _token = ""
    return _token or ""


def token_ok(candidate: str | None) -> bool:
    """Constant-time compare of a supplied token against the current one."""
    expected = get_token()
    return bool(expected) and bool(candidate) and secrets.compare_digest(candidate, expected)
