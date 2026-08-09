"""Push-to-talk combo matching: the combo must fire on an EXACT key set, so a
larger chord (e.g. Win+Shift+Ctrl) never triggers a Win+Shift binding."""
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
    svc.refresh_config()              # populate the cached bindings _on_event reads
    calls = {"start": 0, "stop": 0}
    svc.on_ptt_start = lambda: calls.__setitem__("start", calls["start"] + 1)
    svc.on_ptt_stop = lambda: calls.__setitem__("stop", calls["stop"] + 1)
    svc._dispatch = lambda cb: cb()   # run callbacks synchronously in-test
    return svc, calls


def test_exact_combo_triggers(monkeypatch):
    svc, calls = _make(monkeypatch)
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    assert calls["start"] == 1
    svc._on_event(_evt("left shift", "up"))
    assert calls["stop"] == 1


def test_extra_modifier_does_not_trigger(monkeypatch):
    svc, calls = _make(monkeypatch)
    svc._on_event(_evt("left ctrl", "down"))
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    assert calls["start"] == 0   # Win+Shift+Ctrl must not fire a Win+Shift binding


def test_extra_key_pressed_after_combo_keeps_recording(monkeypatch):
    """Strict to START, lenient to CONTINUE: once recording, an extra key that
    joins the chord shouldn't stop it — only dropping a combo key does."""
    svc, calls = _make(monkeypatch)
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    assert calls["start"] == 1
    svc._on_event(_evt("left ctrl", "down"))     # extra key mid-hold
    assert calls["stop"] == 0                    # still recording
    svc._on_event(_evt("left windows", "up"))    # drop a combo key
    assert calls["stop"] == 1


def test_event_updates_liveness_heartbeat(monkeypatch):
    svc, _ = _make(monkeypatch)
    svc._last_seen = 0.0
    svc._on_event(_evt("a", "down"))
    assert svc._last_seen > 0.0                  # watchdog can tell the hook is live


def test_hook_alive_detects_live_and_dead(monkeypatch):
    svc, _ = _make(monkeypatch)
    # A live hook would run _on_event for the canary and bump the heartbeat.
    monkeypatch.setattr(svc, "_inject_canary",
                        lambda: setattr(svc, "_last_seen", svc._last_seen + 1))
    assert svc._hook_alive() is True
    # A dead hook sees nothing, so the heartbeat never moves.
    monkeypatch.setattr(svc, "_inject_canary", lambda: None)
    assert svc._hook_alive() is False
