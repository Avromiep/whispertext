"""Local, estimated spend tracking for the pay-per-use streaming engines.

This is WhisperText's OWN usage only — a no-extra-key estimate from how much audio
it transcribed times the per-hour rate — NOT your account bill (which also includes
any other projects/keys; see the provider console for that total). Tallies are kept
per UTC day so a rolling "past 30 days" and an all-time total are both accurate.
Legacy per-month entries (older format) are still counted toward the totals.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from backend.config import APP_DIR
from backend.utils.logger import get_logger

log = get_logger(__name__)

USAGE_FILE = APP_DIR / "usage.json"
_lock = threading.Lock()

# USD per hour of audio (streaming) per engine, for the estimate.
RATES = {"grok": 0.20, "deepgram": 0.46}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record(engine: str, seconds: float) -> None:
    """Add `seconds` of transcribed audio to today's tally for `engine`."""
    if engine not in RATES or seconds <= 0:
        return
    with _lock:
        data = _load()
        day = data.setdefault(_today(), {})
        day[engine] = round(float(day.get(engine, 0.0)) + seconds, 2)
        try:
            USAGE_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception as exc:
            log.debug("usage write failed: %s", exc)


def _key_date(key: str):
    """Parse a bucket key: new daily 'YYYY-MM-DD', or legacy monthly 'YYYY-MM'
    (dated to the 1st). None if unparseable."""
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(key, fmt).date()
        except ValueError:
            continue
    return None


def summary(engine: str) -> dict:
    """WhisperText's own estimated spend for `engine`: all-time and rolling 30 days."""
    rate = RATES.get(engine, 0.0)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
    all_s = 0.0
    d30_s = 0.0
    for key, engines in _load().items():
        if not isinstance(engines, dict):
            continue
        s = float(engines.get(engine, 0.0))
        if s <= 0:
            continue
        all_s += s
        d = _key_date(key)
        if d is not None and d >= cutoff:
            d30_s += s
    return {
        "engine": engine,
        "rate_per_hour": rate,
        "all_time_usd": round(all_s / 3600 * rate, 2),
        "all_time_minutes": round(all_s / 60, 1),
        "days30_usd": round(d30_s / 3600 * rate, 2),
        "days30_minutes": round(d30_s / 60, 1),
    }
