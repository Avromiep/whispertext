"""Local, estimated spend tracking for the pay-per-use streaming engines.

The provider's console is the authoritative bill; this is a no-extra-key estimate
computed from how much audio was actually transcribed by an engine this calendar
month times its per-hour rate. Persisted to a tiny JSON file next to settings.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from backend.config import APP_DIR
from backend.utils.logger import get_logger

log = get_logger(__name__)

USAGE_FILE = APP_DIR / "usage.json"
_lock = threading.Lock()

# USD per hour of audio (streaming) per engine, for the estimate.
RATES = {"grok": 0.20, "deepgram": 0.46}


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record(engine: str, seconds: float) -> None:
    """Add `seconds` of transcribed audio to this month's tally for `engine`."""
    if engine not in RATES or seconds <= 0:
        return
    with _lock:
        data = _load()
        month = data.setdefault(_month(), {})
        month[engine] = round(float(month.get(engine, 0.0)) + seconds, 2)
        try:
            USAGE_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception as exc:
            log.debug("usage write failed: %s", exc)


def summary(engine: str) -> dict:
    """Estimated spend for `engine` this calendar month."""
    seconds = float(_load().get(_month(), {}).get(engine, 0.0))
    rate = RATES.get(engine, 0.0)
    return {"engine": engine, "month": _month(),
            "seconds": round(seconds, 1),
            "minutes": round(seconds / 60, 1),
            "rate_per_hour": rate,
            "estimated_usd": round(seconds / 3600 * rate, 2)}
