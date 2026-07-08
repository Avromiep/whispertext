"""SQLite storage for dictation history. WAL mode, thread-safe via connection-per-call."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from backend.config import DB_FILE
from backend.utils.logger import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    app TEXT NOT NULL DEFAULT '',
    raw_transcript TEXT NOT NULL,
    final_text TEXT NOT NULL,
    duration_s REAL NOT NULL DEFAULT 0,
    provider TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    favorite INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts DESC);
"""


class HistoryStore:
    def __init__(self, db_path: Path = DB_FILE) -> None:
        self._path = db_path
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add(self, *, app: str, raw: str, final: str, duration_s: float,
            provider: str, language: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO history (ts, app, raw_transcript, final_text, duration_s,"
                " provider, language) VALUES (?,?,?,?,?,?,?)",
                (time.time(), app, raw, final, duration_s, provider, language))
            return int(cur.lastrowid or 0)

    def list(self, *, search: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
        q = ("SELECT * FROM history WHERE final_text LIKE ? OR raw_transcript LIKE ?"
             " OR app LIKE ? ORDER BY ts DESC LIMIT ? OFFSET ?")
        like = f"%{search}%"
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, (like, like, like, limit, offset))]

    def set_favorite(self, entry_id: int, fav: bool) -> None:
        with self._conn() as c:
            c.execute("UPDATE history SET favorite=? WHERE id=?", (int(fav), entry_id))

    def delete(self, entry_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM history WHERE id=?", (entry_id,))

    def clear(self) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM history")

    def purge_older_than(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        with self._conn() as c:
            cur = c.execute("DELETE FROM history WHERE ts < ? AND favorite=0", (cutoff,))
            n = cur.rowcount
        if n:
            log.info("Purged %d history entries older than %d days", n, days)
        return n

    def stats(self) -> dict:
        day_ago = time.time() - 86400
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) n FROM history").fetchone()["n"]
            today = c.execute("SELECT COUNT(*) n FROM history WHERE ts > ?",
                              (day_ago,)).fetchone()["n"]
            avg = c.execute("SELECT AVG(duration_s) a FROM history").fetchone()["a"]
        return {"total": total, "today": today, "avg_duration_s": round(avg or 0, 2)}
