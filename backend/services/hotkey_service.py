"""Global hotkey service using a low-level Windows keyboard hook.

Supports (per spec):
  * Hold Win+Shift            -> push-to-talk (record while held)
  * Double-tap Right Ctrl     -> toggle hands-free recording
  * Configurable combos, double-tap window, and re-binding at runtime.

Windows silently drops a low-level keyboard hook if its callback ever stalls
past the system hook timeout, and also across some session events (lock/unlock,
UAC's secure desktop, sleep/resume) — with no error, and the `keyboard` library
does not re-arm itself. So the callback is kept minimal (no per-event settings
read) and a watchdog probes the hook and reinstalls it if it has gone deaf.
"""
from __future__ import annotations

import ctypes
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

_WATCHDOG_INTERVAL_S = 10.0
_KEYEVENTF_KEYUP = 0x0002
# An unassigned virtual-key: apps ignore a stray key-up for it, but a live
# low-level hook still sees it — so it's a safe liveness canary.
_CANARY_VK = 0xE8


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
        self._last_seen = 0.0                 # heartbeat: last time _on_event ran
        self._watchdog: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        # Cached hotkey config, refreshed off the hot path so the hook callback
        # never does a settings-file read (that per-event work was a stall risk).
        self._combo: set[str] = set()
        self._toggle_key = ""
        self._hands_free_enabled = True
        self._double_tap_ms = 350

    # ------------------------------------------------------------------ control
    def refresh_config(self) -> None:
        """Reload the cached hotkey bindings. Call after a settings change so a
        rebind takes effect immediately (the watchdog also refreshes periodically)."""
        try:
            hk = load_settings().hotkeys
            self._combo = {_norm(p.strip()) for p in hk.push_to_talk.split("+")}
            self._toggle_key = _norm(hk.toggle_key)
            self._hands_free_enabled = hk.hands_free_enabled
            self._double_tap_ms = hk.double_tap_window_ms
        except Exception:
            log.exception("Hotkey config refresh failed; keeping previous bindings")

    def start(self) -> None:
        self.refresh_config()
        if self._hook is None:
            self._hook = keyboard.hook(self._on_event)
            self._last_seen = time.monotonic()
            log.info("Global hotkey hook installed")
        if self._watchdog is None:
            self._watchdog_stop.clear()
            self._watchdog = threading.Thread(target=self._watchdog_loop,
                                              name="hotkey-watchdog", daemon=True)
            self._watchdog.start()

    def stop(self) -> None:
        self._watchdog_stop.set()
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            # Forget any in-flight key state. While paused we ignore events, so a
            # key-up that happens during the pause is never seen; clearing here
            # means it can't act on resume (spuriously stop, or leave a phantom
            # key that blocks the next exact-combo match).
            with self._lock:
                self._down.clear()
                self._ptt_active = False
                self._tap_armed = False
        log.info("Hotkeys %s", "paused" if paused else "resumed")

    # ------------------------------------------------------------------- events
    def _on_event(self, event: keyboard.KeyboardEvent) -> None:
        self._last_seen = time.monotonic()    # liveness heartbeat (before any early return)
        if self._paused or event.name is None:
            return
        name = _norm(event.name)
        combo = self._combo
        toggle_key = self._toggle_key

        with self._lock:
            if event.event_type == "down":
                self._down.add(name)
                # Push-to-talk: fire once when EXACTLY the combo is held — no
                # extra keys. Using == (not subset <=) means Win+Shift+Ctrl does
                # not trigger a Win+Shift binding, so the combo can't fire as a
                # side effect of a larger shortcut the user meant for another app.
                if not self._ptt_active and combo and combo == self._down:
                    self._ptt_active = True
                    self._dispatch(self.on_ptt_start)
                # Double-tap detection for hands-free toggle (skippable).
                if self._hands_free_enabled and name == toggle_key:
                    now = time.monotonic()
                    if self._tap_armed and (now - self._last_tap) * 1000 <= self._double_tap_ms:
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

    # ---------------------------------------------------------------- watchdog
    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(_WATCHDOG_INTERVAL_S):
            try:
                self.refresh_config()
                # Only probe when idle: paused (typing) or keys held would make
                # the check ambiguous, and the hook is plainly alive then anyway.
                if self._paused or self._down:
                    continue
                if not self._hook_alive():
                    log.warning("Hotkey hook stopped responding — reinstalling")
                    self._reinstall_hook()
            except Exception:
                log.exception("Hotkey watchdog error")

    @staticmethod
    def _inject_canary() -> None:
        ctypes.windll.user32.keybd_event(_CANARY_VK, 0, _KEYEVENTF_KEYUP, 0)

    def _hook_alive(self) -> bool:
        before = self._last_seen
        try:
            self._inject_canary()
        except Exception:
            return True   # can't probe — assume alive rather than churn the hook
        time.sleep(0.06)
        return self._last_seen != before

    def _reinstall_hook(self) -> None:
        try:
            if self._hook is not None:
                keyboard.unhook(self._hook)
        except Exception:
            pass
        self._hook = None
        # Force the keyboard library to spin up a fresh OS-level hook rather than
        # just re-registering a handler on a listener whose hook Windows dropped.
        try:
            keyboard._listener.listening = False
        except Exception:
            pass
        try:
            self._hook = keyboard.hook(self._on_event)
            self._last_seen = time.monotonic()
            with self._lock:
                self._down.clear()
                self._ptt_active = False
                self._tap_armed = False
            log.info("Global hotkey hook reinstalled")
        except Exception:
            log.exception("Failed to reinstall hotkey hook")

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
