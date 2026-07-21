"""In-process pub/sub bridging backend threads to WebSocket clients.

Pipeline stages publish events from worker threads; the FastAPI WebSocket
endpoint consumes them from an asyncio queue and pushes them to the Electron
overlay + settings UI in real time.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from backend.utils.logger import get_logger

log = get_logger(__name__)

# Overlay state machine: idle -> listening -> transcribing -> cleaning -> typing -> done
EVENT_TYPES = {"status", "audio_level", "partial", "error", "notification",
               "settings_changed", "model_download", "test_result"}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_status: str | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[str]:
        """New client queue, pre-seeded with the current status.

        The overlay is driven entirely by status events, so a client that
        connects (or reconnects) mid-dictation would otherwise sit blank until
        the *next* state change — recording with no pill on screen.
        """
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        if self._last_status is not None:
            q.put_nowait(self._last_status)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subscribers.discard(q)

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Thread-safe publish; callable from any worker thread."""
        payload = json.dumps({"type": event_type, "ts": time.time(), **(data or {})})
        if event_type == "status":
            self._last_status = payload
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._fanout, payload, event_type)

    def _fanout(self, payload: str, event_type: str = "") -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # A backed-up client must never lose a state transition. Mic
                # levels arrive ~33/s and are purely cosmetic, so drop those
                # instead — both the incoming one and, to make room for a real
                # event, whatever is already queued.
                if event_type == "audio_level":
                    continue
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    # Convenience helpers -----------------------------------------------------
    def status(self, state: str, **extra: Any) -> None:
        self.publish("status", {"state": state, **extra})

    def notify(self, message: str, kind: str = "info") -> None:
        self.publish("notification", {"message": message, "kind": kind})

    def error(self, message: str, **extra: Any) -> None:
        log.error("UI error event: %s", message)
        self.publish("error", {"message": message, **extra})


bus = EventBus()
