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
# The same physical key can't fire two identical events this close together — a
# real double-tap is 100ms+, auto-repeat 30ms+ — so an identical event within
# this window is a duplicate delivery (e.g. from a doubled hook) and is dropped.
# This makes hook duplication harmless: a single press can never read as a
# double-tap, and a combo can't fire twice.
_DEDUP_WINDOW_S = 0.010
# Cap hook reinstalls so a mis-firing liveness probe can't spawn listeners without
# bound; recovery needs only a couple of tries, and dedup covers any that linger.
_MAX_REINSTALLS = 3
# After the push-to-talk combo is held, wait this long before actually starting.
# If another key joins in that window it's a larger shortcut (e.g. Win+Shift+T),
# not dictation, so recording is skipped. Short enough to feel instant.
_PTT_CHORD_WINDOW_S = 0.06
# Only a DELIBERATE release ends a recording: when the combo reads as released,
# wait this long and re-check live key state before stopping. A pause-relax of the
# grip, or a brief GetAsyncKeyState hiccup during a thinking pause, would otherwise
# end a recording mid-sentence while the user is still holding. This is a direct
# trade-off — longer tolerates longer pause-relaxes but adds delay to EVERY release
# (very noticeable on one-word dictations); shorter is snappier but a long relax can
# cut off. 0.35s is the balance point; tunable / could become a user slider.
_PTT_RELEASE_GRACE_S = 0.35
# An unassigned virtual-key: apps ignore a stray key-up for it, but a live
# low-level hook still sees it — so it's a safe liveness canary.
_CANARY_VK = 0xE8
# Windows counts ANY injected input as user activity, so the canary keeps
# resetting the display-sleep timer and the monitor never turns off. Once the
# user has been idle this long, stop injecting so the screen can sleep. Injected
# input can't be exempted from the idle timer, so not-injecting is the only way.
# Must be well under any sane display timeout.
_PROBE_IDLE_CUTOFF_S = 30.0


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = (("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint))

# Modifier families and the virtual-keys (L/R) that count as that family held.
# Matching reads live state via GetAsyncKeyState, so a stale key left in the
# tracked set by a missed key-up can neither wedge the combo (dead hotkey) nor
# count as a phantom "extra" that blocks it.
_FAMILY_VKS = {
    "win":   (0x5B, 0x5C),
    "shift": (0xA0, 0xA1),
    "ctrl":  (0xA2, 0xA3),
    "alt":   (0xA4, 0xA5),
}
_NAME_FAMILY = {
    "windows": "win", "shift": "shift", "alt": "alt",
    "left ctrl": "ctrl", "right ctrl": "ctrl", "ctrl": "ctrl",
}


def _norm(name: str) -> str:
    return _ALIASES.get(name.lower(), name.lower())


class HotkeyService:
    """Callbacks: on_ptt_start/on_ptt_stop (hold) and on_toggle (double-tap)."""

    def __init__(self) -> None:
        self.on_ptt_start: Callable[[], None] = lambda: None
        self.on_ptt_stop: Callable[[], None] = lambda: None
        self.on_toggle: Callable[[], None] = lambda: None
        self.on_clipboard_insert: Callable[[], None] = lambda: None
        self._down: set[str] = set()
        self._ptt_active = False
        self._insert_held = False             # insert key down (debounce OS key-repeat)
        self._insert_hook = None              # dedicated suppressing hook for the insert key
        self._last_tap = 0.0
        self._tap_armed = False
        self._hook = None
        self._lock = threading.Lock()
        self._paused = False
        self._last_seen = 0.0                 # heartbeat: last time _on_event ran
        self._watchdog: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._dedup_key: tuple | None = None  # (name, event_type) of the last event
        self._dedup_t = 0.0
        self._canary_fails = 0                # consecutive liveness-probe misses
        self._reinstalls = 0                  # total hook reinstalls this run (capped)
        self._last_real_input = time.monotonic()  # last REAL key (canary excluded)
        self._idle_since: float | None = None     # when we suspended the canary probe
        self._ptt_pending = False                 # combo held, waiting out the chord window
        self._ptt_timer: threading.Timer | None = None
        self._stop_timer: threading.Timer | None = None   # release-grace re-check timer
        self._ptt_started_at = 0.0                # for logging a suspiciously early stop
        # Cached hotkey config, refreshed off the hot path so the hook callback
        # never does a settings-file read (that per-event work was a stall risk).
        self._combo: set[str] = set()
        self._toggle_key = ""
        self._insert_key = "n"                # clipboard-insert key (Win+Shift+N)
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
            self._insert_key = _norm(hk.clipboard_insert_key)
            # Hands-free (double-tap toggle) was removed from the UI; hard-disable
            # it here so a stored hands_free_enabled=True (or a bare-modifier
            # toggle key like Alt) can never fire a recording by accident.
            self._hands_free_enabled = False
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
            self._cancel_pending_ptt()
            self._cancel_release_check()      # a pending re-check must not fire post-pause
            self._unregister_insert_hook()    # don't keep suppressing N while paused
            with self._lock:
                self._down.clear()
                self._ptt_active = False
                self._tap_armed = False
        log.info("Hotkeys %s", "paused" if paused else "resumed")

    # --------------------------------------------------------- live key state
    def _async_down(self, vk: int) -> bool:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def _family_held(self, family: str) -> bool:
        return any(self._async_down(vk) for vk in _FAMILY_VKS[family])

    def _combo_held(self, combo: set[str]) -> bool:
        """Is every key of the combo physically down right now? Modifier keys are
        read from live state (immune to a missed key-up); any non-modifier key
        falls back to the tracked set."""
        for key in combo:
            fam = _NAME_FAMILY.get(key)
            if fam is not None:
                if not self._family_held(fam):
                    return False
            elif key not in self._down:
                return False
        return True

    def _extra_modifier_held(self, combo: set[str]) -> bool:
        """Is a modifier OUTSIDE the combo physically down? (Win+Shift+Ctrl must
        not fire a Win+Shift binding.) Live state, so a phantom can't block it."""
        allowed = {_NAME_FAMILY[k] for k in combo if k in _NAME_FAMILY}
        return any(self._family_held(f) for f in _FAMILY_VKS if f not in allowed)

    # ------------------------------------------------------------------- events
    def _on_event(self, event: keyboard.KeyboardEvent) -> None:
        now = time.monotonic()
        self._last_seen = now                 # liveness heartbeat (before any early return)
        if self._paused or event.name is None:
            return
        # A real key (the canary has name None, so it's already excluded above).
        # Marks genuine user activity so the watchdog can stop injecting when idle.
        self._last_real_input = now
        # Drop a duplicate delivery of the same event (e.g. if a hook ever got
        # doubled) so one physical press is never processed twice — otherwise a
        # single tap could register as a double-tap and fire recording.
        ev_key = (event.name, event.event_type)
        if ev_key == self._dedup_key and (now - self._dedup_t) < _DEDUP_WINDOW_S:
            return
        self._dedup_key = ev_key
        self._dedup_t = now
        name = _norm(event.name)
        combo = self._combo
        toggle_key = self._toggle_key

        with self._lock:
            if event.event_type == "down":
                self._down.add(name)
                # Push-to-talk: when a combo key completes the chord (whole combo
                # physically held, no extra modifier), don't fire immediately —
                # arm a short timer. If another key joins within the window it's a
                # bigger shortcut (e.g. Win+Shift+T for PowerToys), not dictation,
                # so cancel. Live key state (not the tracked set) is used so a
                # stale key from a missed key-up can't wedge the combo.
                if (not self._ptt_active and not self._ptt_pending and combo and name in combo
                        and self._combo_held(combo)
                        and not self._extra_modifier_held(combo)):
                    self._ptt_pending = True
                    self._ptt_timer = threading.Timer(_PTT_CHORD_WINDOW_S, self._ptt_commit)
                    self._ptt_timer.daemon = True
                    self._ptt_timer.start()
                elif self._ptt_pending and name not in combo:
                    self._cancel_pending_ptt()   # extra key -> a chord, not dictation
                # The clipboard-insert key (e.g. N) is handled by a dedicated
                # suppressing hook installed while recording (_on_insert_key), not
                # here — a plain observing hook can't stop it leaking to the app.
                # Double-tap detection for hands-free toggle (skippable).
                if self._hands_free_enabled and name == toggle_key:
                    now = time.monotonic()
                    if self._tap_armed and (now - self._last_tap) * 1000 <= self._double_tap_ms:
                        self._tap_armed = False
                        log.info("hands-free toggle fired by double-tap %r", name)
                        self._dispatch(self.on_toggle)
                    else:
                        self._tap_armed = True
                        self._last_tap = now
                else:
                    self._tap_armed = False  # any other key breaks the double-tap
            else:  # key up
                self._down.discard(name)
                if self._ptt_pending and not self._combo_held(combo):
                    self._cancel_pending_ptt()   # released before the window elapsed
                if self._ptt_active and not self._combo_held(combo):
                    self._arm_release_check()    # confirm after a grace period, don't stop on a blip

    @staticmethod
    def _dispatch(cb: Callable[[], None]) -> None:
        # Never block the low-level hook thread — Windows will drop the hook
        # if the callback stalls, so real work happens on a worker thread.
        threading.Thread(target=cb, daemon=True).start()

    def _cancel_pending_ptt(self) -> None:
        self._ptt_pending = False
        if self._ptt_timer is not None:
            self._ptt_timer.cancel()
            self._ptt_timer = None

    def _cancel_release_check(self) -> None:
        if self._stop_timer is not None:
            self._stop_timer.cancel()
            self._stop_timer = None

    def _arm_release_check(self) -> None:
        """The combo just read as released: re-check after a short grace instead of
        stopping now, so a momentary GetAsyncKeyState blip (or a fingertip lift)
        can't end a recording the user is still holding. Assumes the lock is held."""
        if self._stop_timer is not None:
            return   # a re-check is already pending
        self._stop_timer = threading.Timer(_PTT_RELEASE_GRACE_S, self._ptt_release_check)
        self._stop_timer.daemon = True
        self._stop_timer.start()

    def _ptt_release_check(self) -> None:
        """Grace elapsed: stop only if the combo is STILL not held (a real release).
        If it came back, it was a blip — keep recording."""
        with self._lock:
            self._stop_timer = None
            if not self._ptt_active or self._combo_held(self._combo):
                return   # not recording, or the combo returned — a blip; keep going
            held = time.monotonic() - self._ptt_started_at
            keys = {k: self._combo_held({k}) for k in self._combo}
            self._ptt_active = False
            self._insert_held = False
            self._unregister_insert_hook()
            self._dispatch(self.on_ptt_stop)
        # Diagnostic: every real stop, with hold time + which combo key read as up.
        log.info("PTT stop (key-event): held %.2fs, keys=%s", held, keys)

    def _on_insert_key(self, event) -> None:
        """Dedicated suppressing hook for the insert key while recording: fires
        the clipboard insert AND stops the key reaching the app. Handles both
        down and up so OS key-repeat fires it only once per physical press."""
        if getattr(event, "event_type", None) == "up":
            self._insert_held = False
            return
        if self._ptt_active and not self._insert_held:
            self._insert_held = True
            log.info("clipboard-insert key during dictation")
            self._dispatch(self.on_clipboard_insert)

    def _register_insert_hook(self) -> None:
        """Install the suppressing insert-key hook for the duration of a
        recording, so N (etc.) triggers a clipboard splice and never leaks."""
        self._insert_held = False
        try:
            if self._insert_hook is None and self._insert_key:
                self._insert_hook = keyboard.hook_key(
                    self._insert_key, self._on_insert_key, suppress=True)
        except Exception as exc:
            log.debug("register insert hook failed: %s", exc)

    def _unregister_insert_hook(self) -> None:
        hook = self._insert_hook
        self._insert_hook = None
        self._insert_held = False
        if hook is None:
            return
        try:
            keyboard.unhook(hook)
        except Exception:
            try:
                keyboard.unhook_key(self._insert_key)
            except Exception as exc:
                log.debug("unregister insert hook failed: %s", exc)

    def _ptt_commit(self) -> None:
        """Fires after the chord window with no extra key — start recording."""
        with self._lock:
            if not self._ptt_pending:
                return
            self._ptt_pending = False
            self._ptt_timer = None
            if not (self._combo and self._combo_held(self._combo)
                    and not self._extra_modifier_held(self._combo)):
                return   # combo released or an extra modifier joined during the wait
            self._ptt_active = True
            self._ptt_started_at = time.monotonic()
        self._register_insert_hook()              # stop the insert key leaking to apps
        log.info("push-to-talk fired (down=%s)", sorted(self._down))
        self._dispatch(self.on_ptt_start)

    # ---------------------------------------------------------------- watchdog
    def _os_idle_seconds(self) -> float:
        """Seconds since the last system-wide input (keyboard OR mouse) per
        Windows' GetLastInputInfo. Our own canary counts toward this too, so it
        only means 'no real input' once we've stopped injecting."""
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return max(0.0, ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0)

    def _skip_probe_when_idle(self, now: float) -> bool:
        """True when the liveness canary should be suppressed because the user is
        idle — so it stops resetting the display-sleep timer and the monitor can
        turn off.

        Keyboard idle (`_last_real_input`) is the clean trigger to stop, since it
        excludes our own canary. Once suspended we no longer inject, so the OS
        idle clock runs clean; if it shows input arriving AFTER we suspended (a
        mouse move the keyboard hook can't see), we resume — so a hook that died
        while idle is still reinstalled before the user reaches for push-to-talk."""
        if now - self._last_real_input < _PROBE_IDLE_CUTOFF_S:
            self._idle_since = None                       # keyboard active — keep probing
            return False
        if self._idle_since is None:
            self._idle_since = now                        # keyboard just went idle — suspend
        elif self._os_idle_seconds() < now - self._idle_since:
            self._idle_since = None                       # real OS input since — resume
            return False
        return True

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(_WATCHDOG_INTERVAL_S):
            try:
                self.refresh_config()
                if self._paused:
                    continue
                # Rescue a recording stuck on a missed key-up: if we think we're
                # holding but the combo isn't physically down, end it — but confirm
                # after the release grace first, so a transient key-state blip at a
                # watchdog tick can't end a recording the user is still holding.
                if self._ptt_active and not self._combo_held(self._combo):
                    time.sleep(_PTT_RELEASE_GRACE_S)
                    if self._ptt_active and not self._combo_held(self._combo):
                        held = time.monotonic() - self._ptt_started_at
                        keys = {k: self._combo_held({k}) for k in self._combo}
                        with self._lock:
                            was_active, self._ptt_active = self._ptt_active, False
                        if was_active:
                            self._unregister_insert_hook()
                            self._dispatch(self.on_ptt_stop)
                            log.info("PTT stop (watchdog): held %.2fs, keys=%s", held, keys)
                    continue
                if self._ptt_active:
                    continue   # actively recording — the hook is obviously alive
                if self._skip_probe_when_idle(time.monotonic()):
                    continue   # user idle — don't inject, so the display can sleep
                if self._hook_alive():
                    self._canary_fails = 0
                    continue
                # Require two misses in a row before reinstalling: a single flaky
                # probe shouldn't churn the hook. Cap total reinstalls so a probe
                # that never registers can't spawn listeners without bound.
                self._canary_fails += 1
                if self._canary_fails >= 2 and self._reinstalls < _MAX_REINSTALLS:
                    log.warning("Hotkey hook not responding (x%d) — reinstalling", self._canary_fails)
                    self._reinstalls += 1
                    self._canary_fails = 0
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
            self._cancel_pending_ptt()
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
