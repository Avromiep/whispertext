"""Global hotkey service using a low-level Windows keyboard hook.

Supports (per spec):
  * Hold Win+Shift            -> push-to-talk (record while held)
  * Double-tap Right Ctrl     -> toggle hands-free recording
  * Configurable combos, double-tap window, and re-binding at runtime.

The hook thread does near-zero work while idle (<20 ms dispatch latency).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

import keyboard

from backend.models.settings import load_settings
from backend.utils.logger import get_logger

log = get_logger(__name__)

# Normalize the many names Windows reports for modifier keys.
_ALIASES = {
    "left windows": "windows", "right windows": "windows",
    "left shift": "shift", "right shift": "shift",
    "left alt": "alt", "alt gr": "alt",
    "left ctrl": "left ctrl", "right ctrl": "right ctrl",
}


def _norm(name: str) -> str:
    return _ALIASES.get(name.lower(), name.lower())


class HotkeyService:
    """Callbacks: on_ptt_start/on_ptt_stop (hold) and on_toggle (double-tap)."""

    def __init__(self) -> None:
        self.on_ptt_start: Callable[[], None] = lambda: None
        self.on_ptt_stop: Callable[[], None] = lambda: None
        self.on_toggle: Callable[[], None] = lambda: None
        self._down: set[str] = set()
        self._ptt_active = False
        self._last_tap = 0.0
        self._tap_armed = False
        self._hook = None
        self._lock = threading.Lock()
        self._paused = False

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        if self._hook is None:
            self._hook = keyboard.hook(self._on_event)
            log.info("Global hotkey hook installed")

    def stop(self) -> None:
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        log.info("Hotkeys %s", "paused" if paused else "resumed")

    # ------------------------------------------------------------------- events
    def _on_event(self, event: keyboard.KeyboardEvent) -> None:
        if self._paused or event.name is None:
            return
        name = _norm(event.name)
        hk = load_settings().hotkeys
        combo = {_norm(p.strip()) for p in hk.push_to_talk.split("+")}
        toggle_key = _norm(hk.toggle_key)

        with self._lock:
            if event.event_type == "down":
                self._down.add(name)
                # Push-to-talk: fire once when the full combo is first held.
                if not self._ptt_active and combo and combo <= self._down:
                    self._ptt_active = True
                    self._dispatch(self.on_ptt_start)
                # Double-tap detection for hands-free toggle (skippable).
                if hk.hands_free_enabled and name == toggle_key:
                    now = time.monotonic()
                    if self._tap_armed and (now - self._last_tap) * 1000 <= hk.double_tap_window_ms:
                        self._tap_armed = False
                        self._dispatch(self.on_toggle)
                    else:
                        self._tap_armed = True
                        self._last_tap = now
                else:
                    self._tap_armed = False  # any other key breaks the double-tap
            else:  # key up
                self._down.discard(name)
                if self._ptt_active and not (combo <= self._down):
                    self._ptt_active = False
                    self._dispatch(self.on_ptt_stop)

    @staticmethod
    def _dispatch(cb: Callable[[], None]) -> None:
        # Never block the low-level hook thread — Windows will drop the hook
        # if the callback stalls, so real work happens on a worker thread.
        threading.Thread(target=cb, daemon=True).start()

    # ------------------------------------------------------------- shortcut rec
    @staticmethod
    def record_shortcut(timeout_s: float = 10.0) -> str | None:
        """Block until the user presses a combo; used by 'Record New Shortcut'."""
        try:
            combo = keyboard.read_hotkey(suppress=False)
            return combo
        except Exception:
            log.exception("Shortcut recording failed")
            return None


hotkey_service = HotkeyService()
