"""Controller-rumble service (buzz patterns + styles) and the audio capture-start
hook that drives it.

Never touches the real XInput DLL — a FakeBackend is injected, or ctypes.WinDLL
is patched to fail. No test sleeps for a real buzz: pulse's waits run through a
FakeEvent (records the seconds) except one bounded real-Event worker test.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from pathlib import Path

import backend.models.settings as settings_mod
import backend.services.rumble_service as rs
from backend.models.settings import AudioSettings, Settings
from backend.services.rumble_service import (
    FULL, RumbleService, XInputBackend,
    XINPUT_GAMEPAD, XINPUT_STATE, XINPUT_VIBRATION,
)
from backend.tests.test_audio_warm import _block, _setup

_LOGGER = "backend.services.rumble_service"


class FakeBackend:
    """Records calls instead of touching XInput. `slot` is first_connected's
    result (None = no controller). `set_codes` is an optional list of return codes
    for set_motors (default 0). raise_on_nonzero raises on a non-zero write."""

    def __init__(self, slot=0, set_codes=None, raise_on_nonzero=False):
        self.slot = slot
        self.calls: list[tuple[int, int, int]] = []
        self.stop_all_calls = 0
        self._codes = list(set_codes) if set_codes else None
        self.raise_on_nonzero = raise_on_nonzero

    def first_connected(self):
        return self.slot

    def set_motors(self, slot, left, right):
        if self.raise_on_nonzero and (left or right):
            raise RuntimeError("set_motors boom")
        self.calls.append((slot, left, right))
        if self._codes:
            return self._codes.pop(0)
        return 0

    def stop_all(self):
        self.stop_all_calls += 1


class FakeEvent:
    """Stand-in for threading.Event: wait() records seconds and returns False
    (no stop) unless stop_after is reached or on_wait sets it. Lets pulse() run
    with zero real delay."""

    def __init__(self, stop_after=None, on_wait=None):
        self.waits: list[float] = []
        self._stop_after = stop_after
        self._on_wait = on_wait
        self._is_set = False

    def is_set(self):
        return self._is_set

    def set(self):
        self._is_set = True

    def clear(self):
        self._is_set = False

    def wait(self, secs):
        self.waits.append(secs)
        if self._on_wait:
            self._on_wait(len(self.waits))
        if self._stop_after is not None and len(self.waits) >= self._stop_after:
            self._is_set = True
            return True
        return self._is_set


def _wait_for(cond, timeout: float) -> bool:
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


# ---------------------------------------------------------- capture-start hook

def test_fires_on_first_block_not_on_keypress(monkeypatch):
    svc, _ = _setup(monkeypatch, keep_warm=True)
    n = {"c": 0}
    svc.on_capture_started = lambda: n.__setitem__("c", n["c"] + 1)

    svc.prewarm()
    for _ in range(3):
        svc._audio_callback(_block(), 480, None, None)   # idle pre-roll, not recording
    assert n["c"] == 0                                   # key-down/prewarm must NOT fire

    svc.start()                                          # what the hotkey triggers
    assert n["c"] == 0                                   # no real block yet -> no buzz
    svc._audio_callback(_block(), 480, None, None)
    assert n["c"] == 1                                   # first real block = capture started
    svc._audio_callback(_block(), 480, None, None)
    svc._audio_callback(_block(), 480, None, None)
    assert n["c"] == 1                                   # once per session only

    svc.stop()
    svc.start()
    svc._audio_callback(_block(), 480, None, None)
    assert n["c"] == 2                                   # fresh session fires again
    svc.stop()
    svc._cancel_idle_timer_locked()


def test_hook_exception_does_not_break_capture(monkeypatch):
    svc, _ = _setup(monkeypatch, keep_warm=True)
    svc.on_capture_started = lambda: (_ for _ in ()).throw(RuntimeError("hook boom"))
    svc.start()
    svc._audio_callback(_block(), 480, None, None)       # must not raise
    assert len(svc._chunks) >= 1                         # block still captured
    svc.stop()
    svc._cancel_idle_timer_locked()


# --------------------------------------------------------------- pulse() shapes

def test_pulse_double_calls_and_waits(caplog):
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        svc.pulse("double")
    assert be.calls == [(0, FULL, FULL), (0, 0, 0), (0, FULL, FULL), (0, 0, 0)]
    assert svc._stop_evt.waits == [0.25, 0.15, 0.25]
    assert "Rumble: fired on slot" in caplog.text


def test_pulse_default_matches_default_style():
    assert rs.DEFAULT_STYLE == settings_mod.DEFAULT_VIBRATE_STYLE
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent()
    svc.pulse()                                          # no style -> DEFAULT_STYLE
    expected = [(0, s, s) for s, _ in rs.PATTERNS[rs.DEFAULT_STYLE]] + [(0, 0, 0)]
    assert be.calls == expected


def test_pulse_strong_gentle_and_unknown():
    for style, exp_calls, exp_waits in [
        ("single", [(0, FULL, FULL), (0, 0, 0)], [0.25]),
        ("strong", [(0, FULL, FULL), (0, 0, 0)], [0.40]),
        ("gentle", [(0, 40000, 40000), (0, 0, 0)], [0.20]),
    ]:
        be = FakeBackend(slot=0)
        svc = RumbleService(backend=be)
        svc._stop_evt = FakeEvent()
        svc.pulse(style)
        assert be.calls == exp_calls
        assert svc._stop_evt.waits == exp_waits
    # Unknown style falls back to the default pattern.
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent()
    svc.pulse("loud")
    expected = [(0, s, s) for s, _ in rs.PATTERNS[rs.DEFAULT_STYLE]] + [(0, 0, 0)]
    assert be.calls == expected


def test_pulse_caps(monkeypatch):
    monkeypatch.setitem(rs.PATTERNS, "strong", ((FULL, 10.0), (FULL, 10.0), (FULL, 10.0)))
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent()
    svc.pulse("strong")
    assert all(w <= 0.6 for w in svc._stop_evt.waits)
    assert abs(sum(svc._stop_evt.waits) - 1.0) < 1e-9     # total capped at 1.0s
    assert be.calls[-1] == (0, 0, 0)


def test_pulse_unreachable_rc_stops(caplog):
    be = FakeBackend(slot=0, set_codes=[1167])            # first write "not connected"
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        svc.pulse("double")
    assert be.calls == [(0, FULL, FULL), (0, 0, 0)]       # no further on-writes
    assert be.calls[-1] == (0, 0, 0)
    assert caplog.text.count("not reachable") == 1
    assert "Rumble: fired on slot" not in caplog.text


def test_pulse_stop_mid_pattern(caplog):
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent(stop_after=1)               # stop() during the first wait
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        svc.pulse("double")
    assert be.calls == [(0, FULL, FULL), (0, 0, 0)]
    assert be.calls[-1] == (0, 0, 0)
    assert "Rumble: fired on slot" not in caplog.text


def test_pulse_set_motors_raises_still_zeroes():
    be = FakeBackend(slot=0, raise_on_nonzero=True)
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent()
    svc.pulse("double")                                   # must not raise
    assert be.calls[-1] == (0, 0, 0)


def test_pulse_no_controller_then_hotplug(caplog):
    be = FakeBackend(slot=None)
    svc = RumbleService(backend=be)
    svc._stop_evt = FakeEvent()
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        svc.pulse()
    assert be.calls == []
    assert "Rumble: no controller" in caplog.text
    be.slot = 1                                           # plugged in now (nothing cached)
    svc.pulse()
    assert any(c[0] == 1 and (c[1] or c[2]) for c in be.calls)


def test_request_is_non_blocking():
    svc = RumbleService(backend=FakeBackend())
    t0 = time.perf_counter()
    svc.request()
    svc.request()
    assert time.perf_counter() - t0 < 0.05
    assert svc._thread is None


# ----------------------------------------------------------------- the worker

def test_worker_no_stacking(monkeypatch):
    monkeypatch.setattr(rs.atexit, "register", lambda *a, **k: None)
    monkeypatch.setattr(rs, "load_settings",
                        lambda: Settings(audio=AudioSettings(vibrate_controller_on_record=True)))
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    once = {"done": False}

    def on_wait(_n):
        if not once["done"]:                              # during the first segment,
            once["done"] = True
            for _ in range(3):
                svc.request()                             # pile on 3 more buzz requests
    svc._stop_evt = FakeEvent(on_wait=on_wait)

    pat = rs.PATTERNS[rs.DEFAULT_STYLE]
    total_calls = len(pat) + 1                            # segments + the finally zero
    nonzero = sum(1 for s, _ in pat if s)
    svc.start()
    try:
        svc.request()
        assert _wait_for(lambda: len(be.calls) >= total_calls, 1.0)
        time.sleep(0.05)                                  # a 2nd pattern would show up here
    finally:
        svc.stop()
    assert len(be.calls) == total_calls                   # exactly ONE pattern
    assert sum(1 for c in be.calls if c[1] or c[2]) == nonzero
    assert svc._thread is None


def test_worker_real_event_stop_interrupts(monkeypatch):
    monkeypatch.setattr(rs.atexit, "register", lambda *a, **k: None)
    monkeypatch.setattr(rs, "load_settings",
                        lambda: Settings(audio=AudioSettings(
                            vibrate_controller_on_record=True, vibrate_style="strong")))
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)                       # REAL threading.Event
    svc.start()
    try:
        svc.request()
        assert _wait_for(lambda: (0, FULL, FULL) in be.calls, 1.0)   # strong's 0.4s buzz began
        t0 = time.perf_counter()
        svc.stop()
        assert time.perf_counter() - t0 < 0.2             # stop cut the 0.4s wait short
    finally:
        svc.stop()
    assert be.calls[-1] == (0, 0, 0)
    assert svc._thread is None


def test_worker_disabled(monkeypatch):
    monkeypatch.setattr(rs.atexit, "register", lambda *a, **k: None)
    monkeypatch.setattr(rs, "load_settings",
                        lambda: Settings(audio=AudioSettings(vibrate_controller_on_record=False)))
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    svc.start()
    try:
        svc.request()
        time.sleep(0.15)
    finally:
        svc.stop()
    assert be.calls == []                                 # disabled -> no buzz
    assert be.stop_all_calls == 1                         # cleared once at worker start
    assert svc._thread is None


# -------------------------------------------------------- settings leniency/safety

def test_vibrate_style_defaults_and_lenient():
    assert Settings().audio.vibrate_style == settings_mod.DEFAULT_VIBRATE_STYLE
    assert Settings.model_validate({"audio": {}}).audio.vibrate_style == settings_mod.DEFAULT_VIBRATE_STYLE
    for bad in (None, 5, "weird", [], {}):
        a = Settings.model_validate({"audio": {"vibrate_style": bad}}).audio
        assert a.vibrate_style == settings_mod.DEFAULT_VIBRATE_STYLE
    assert Settings.model_validate({"audio": {"vibrate_style": " Strong "}}).audio.vibrate_style == "strong"


def test_bad_vibrate_style_does_not_wipe_settings(monkeypatch, tmp_path):
    import json
    sf = tmp_path / "settings.json"
    sf.write_text(json.dumps({
        "audio": {"vibrate_style": "loud", "keep_mic_warm": False},
        "vocabulary": {"words": ["GitHub"]},
    }), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", sf)
    monkeypatch.setattr(settings_mod, "SETTINGS_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(settings_mod, "_settings", None)
    monkeypatch.setattr(settings_mod, "_loaded_mtime", None)
    s = settings_mod.load_settings()
    assert s.audio.keep_mic_warm is False                 # not wiped
    assert s.vocabulary.words == ["GitHub"]               # not wiped
    assert s.audio.vibrate_style == settings_mod.DEFAULT_VIBRATE_STYLE   # bad value coerced


# ------------------------------------------------------------------ dll / wiring

def test_xinput_missing_is_noop(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    def boom(*a, **k):
        raise OSError("no xinput")
    monkeypatch.setattr(ctypes, "WinDLL", boom, raising=False)
    be = XInputBackend()
    assert be.first_connected() is None
    assert be.set_motors(0, 1, 1) is None
    be.stop_all()                                         # must not raise


def test_struct_sizes():
    assert ctypes.sizeof(XINPUT_GAMEPAD) == 12
    assert ctypes.sizeof(XINPUT_STATE) == 16
    assert ctypes.sizeof(XINPUT_VIBRATION) == 4


def test_app_wires_rumble_to_capture_not_hotkey():
    backend_dir = Path(__file__).resolve().parents[1]     # .../backend
    app_src = (backend_dir / "app.py").read_text(encoding="utf-8")
    assert "audio_service.on_capture_started = rumble_service.request" in app_src
    for mod in ("services/hotkey_service.py", "services/pipeline.py"):
        assert "rumble" not in (backend_dir / mod).read_text(encoding="utf-8").lower()
