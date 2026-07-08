"""Structured rotating-file + console logging."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from backend.config import LOG_DIR

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False


def setup_logging(debug: bool = False) -> None:
    global _configured
    if _configured:
        logging.getLogger().setLevel(logging.DEBUG if debug else logging.INFO)
        return
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    file_h = logging.handlers.RotatingFileHandler(
        LOG_DIR / "whispertext.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_h.setFormatter(logging.Formatter(_FMT))
    root.addHandler(file_h)

    con = logging.StreamHandler(sys.stderr)
    con.setFormatter(logging.Formatter(_FMT))
    root.addHandler(con)

    # Third-party noise reduction
    for noisy in ("httpx", "httpcore", "urllib3", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
