"""Controller-rumble service + the audio capture-start hook that drives it.

Never touches the real XInput DLL — a FakeBackend is injected, or ctypes.WinDLL
is patched to fail. No test sleeps a real 200 ms (RUMBLE_SECONDS is monkeypatched).
"""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from pathlib import Path

import backend.services.rumble_service as rs
from backend.models.settings import AudioSettings, Settings
from backend.services.rumble_service import (
    MOTOR_STRENGTH, RumbleService, XInputBackend,
    XINPUT_GAMEPAD, XINPUT_STATE, XINPUT_VIBRATION,
)
from backend.tests.test_audio_warm import _block, _setup

_LOGGER = "backend.services.rumble_service"


class FakeBackend:
    """Records calls instead of touching XInput. `slot` is what first_connected
    returns (None = no controller); set it to simulate hot-plugging."""

    def __init__(self, slot=0):
        self.slot = slot
        self.calls: list[tuple[int, int, int]] = []
        self.stop_all_calls = 0
        self.raise_on_nonzero = False

    def first_connected(self):
        return self.slot

    def set_motors(self, slot, left, right):
        if self.raise_on_nonzero and (left or right):
            raise RuntimeError("set_motors boom")
        self.calls.append((slot, left, right))
        return 0

    def stop_all(self):
        self.stop_all_calls += 1


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


# ------------------------------------------------------------------- pulse()

def test_pulse_fires_then_zeroes_and_logs(monkeypatch, caplog):
    be = FakeBackend(slot=2)
    svc = RumbleService(backend=be)
    monkeypatch.setattr(rs, "RUMBLE_SECONDS", 0)
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        svc.pulse()
    assert be.calls == [(2, MOTOR_STRENGTH, MOTOR_STRENGTH), (2, 0, 0)]
    assert "Rumble: fired on slot 2" in caplog.text


def test_hard_cap(monkeypatch):
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    monkeypatch.setattr(rs, "RUMBLE_SECONDS", 10)        # exceeds the cap
    slept = {}
    monkeypatch.setattr(rs.time, "sleep", lambda s: slept.__setitem__("s", s))
    svc.pulse()
    assert slept["s"] == 0.5                             # capped at MAX_RUMBLE_SECONDS


def test_no_controller_then_hotplug(monkeypatch, caplog):
    be = FakeBackend(slot=None)
    svc = RumbleService(backend=be)
    monkeypatch.setattr(rs, "RUMBLE_SECONDS", 0)
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        svc.pulse()
    assert be.calls == []                                # nothing fired
    assert "Rumble: no controller" in caplog.text
    be.slot = 1                                          # plugged in now (nothing cached)
    svc.pulse()
    assert be.calls == [(1, MOTOR_STRENGTH, MOTOR_STRENGTH), (1, 0, 0)]


def test_set_motors_raises_still_zeroes(monkeypatch):
    be = FakeBackend(slot=3)
    be.raise_on_nonzero = True
    svc = RumbleService(backend=be)
    monkeypatch.setattr(rs, "RUMBLE_SECONDS", 0)
    svc.pulse()                                          # must not raise
    assert be.calls[-1] == (3, 0, 0)                     # zeroed in finally


def test_request_is_non_blocking():
    svc = RumbleService(backend=FakeBackend())
    t0 = time.perf_counter()
    svc.request()
    svc.request()
    assert time.perf_counter() - t0 < 0.05               # trivial enqueue, no blocking
    assert svc._thread is None                            # never starts a thread


def test_worker_enabled_and_disabled(monkeypatch):
    monkeypatch.setattr(rs, "RUMBLE_SECONDS", 0)
    monkeypatch.setattr(rs.atexit, "register", lambda *a, **k: None)

    # Enabled -> one buzz (fire + zero).
    be = FakeBackend(slot=0)
    svc = RumbleService(backend=be)
    monkeypatch.setattr(rs, "load_settings",
                        lambda: Settings(audio=AudioSettings(vibrate_controller_on_record=True)))
    svc.start()
    try:
        svc.request()
        assert _wait_for(lambda: len(be.calls) >= 2, 1.0)
    finally:
        svc.stop()
    assert be.calls == [(0, MOTOR_STRENGTH, MOTOR_STRENGTH), (0, 0, 0)]
    assert be.stop_all_calls == 1                         # cleared once at worker start
    assert svc._thread is None                            # exited after stop()

    # Disabled -> no buzz.
    be2 = FakeBackend(slot=0)
    svc2 = RumbleService(backend=be2)
    monkeypatch.setattr(rs, "load_settings",
                        lambda: Settings(audio=AudioSettings(vibrate_controller_on_record=False)))
    svc2.start()
    try:
        svc2.request()
        time.sleep(0.2)                                   # give the worker time to drain
    finally:
        svc2.stop()
    assert be2.calls == []
    assert be2.stop_all_calls == 1
    assert svc2._thread is None


# --------------------------------------------------------------- settings / dll

def test_missing_key_defaults_on():
    s = Settings.model_validate({"audio": {"keep_mic_warm": False}})
    assert s.audio.vibrate_controller_on_record is True


def test_xinput_missing_is_noop(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    def boom(*a, **k):
        raise OSError("no xinput")
    monkeypatch.setattr(ctypes, "WinDLL", boom, raising=False)
    be = XInputBackend()
    assert be.first_connected() is None
    assert be.set_motors(0, 1, 1) is None                # no-op without a DLL
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
        text = (backend_dir / mod).read_text(encoding="utf-8").lower()
        assert "rumble" not in text
