"""Push-to-talk matching. It reads LIVE key state, so:
  * a larger chord (Win+Shift+Ctrl) never triggers a Win+Shift binding, and
  * a stale key left in the tracked set by a missed key-up can neither block the
    combo (dead hotkey) nor count as a phantom extra.
`_family_held` is stubbed per test to stand in for GetAsyncKeyState."""
from __future__ import annotations

import types

from backend.services import hotkey_service as hk_mod
from backend.services.hotkey_service import HotkeyService
from backend.models.settings import HotkeySettings, Settings


def _evt(name: str, kind: str):
    return types.SimpleNamespace(name=name, event_type=kind)


def _make(monkeypatch, combo="windows+shift"):
    s = Settings(hotkeys=HotkeySettings(push_to_talk=combo, hands_free_enabled=False))
    monkeypatch.setattr(hk_mod, "load_settings", lambda: s)
    svc = HotkeyService()
    svc.refresh_config()                      # populate the cached bindings
    held: set[str] = set()                    # modifier families physically down
    svc._family_held = lambda fam: fam in held
    calls = {"start": 0, "stop": 0}
    svc.on_ptt_start = lambda: calls.__setitem__("start", calls["start"] + 1)
    svc.on_ptt_stop = lambda: calls.__setitem__("stop", calls["stop"] + 1)
    svc._dispatch = lambda cb: cb()           # run callbacks synchronously in-test
    return svc, calls, held


def test_exact_combo_triggers_and_releases(monkeypatch):
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    assert calls["start"] == 1
    held.discard("shift")                     # let go of shift
    svc._on_event(_evt("left shift", "up"))
    assert calls["stop"] == 1


def test_extra_modifier_does_not_trigger(monkeypatch):
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift", "ctrl"}          # ctrl also physically held
    svc._on_event(_evt("left ctrl", "down"))
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    assert calls["start"] == 0                # Ctrl is an extra modifier


def test_stale_tracked_key_does_not_block(monkeypatch):
    """A phantom left in the tracked set by a missed key-up must not stop a clean
    press from firing — the regression that killed the hotkey until a restart."""
    svc, calls, held = _make(monkeypatch)
    svc._down.add("shift")                     # ghost from a dropped key-up
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    assert calls["start"] == 1


def test_extra_key_after_combo_keeps_recording(monkeypatch):
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    assert calls["start"] == 1
    held.add("ctrl")                          # extra key mid-hold
    svc._on_event(_evt("left ctrl", "down"))
    assert calls["stop"] == 0                  # still recording (combo still held)
    held.discard("win")
    svc._on_event(_evt("left windows", "up"))  # drop a combo key
    assert calls["stop"] == 1


def test_event_updates_liveness_heartbeat(monkeypatch):
    svc, _, _ = _make(monkeypatch)
    svc._last_seen = 0.0
    svc._on_event(_evt("a", "down"))
    assert svc._last_seen > 0.0                # watchdog can tell the hook is live


def test_hook_alive_detects_live_and_dead(monkeypatch):
    svc, _, _ = _make(monkeypatch)
    monkeypatch.setattr(svc, "_inject_canary",
                        lambda: setattr(svc, "_last_seen", svc._last_seen + 1))
    assert svc._hook_alive() is True
    monkeypatch.setattr(svc, "_inject_canary", lambda: None)
    assert svc._hook_alive() is False
