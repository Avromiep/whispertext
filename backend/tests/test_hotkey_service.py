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
    svc._register_insert_hook = lambda: None  # don't touch the real OS keyboard in tests
    svc._unregister_insert_hook = lambda: None
    return svc, calls, held


def test_exact_combo_triggers_and_releases(monkeypatch):
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    svc._ptt_commit()                          # chord window elapses, only combo held
    assert calls["start"] == 1
    held.discard("shift")                     # let go of shift
    svc._on_event(_evt("left shift", "up"))
    svc._ptt_release_check()                   # release grace elapses, combo still not held
    assert calls["stop"] == 1


def test_extra_modifier_does_not_trigger(monkeypatch):
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift", "ctrl"}          # ctrl also physically held
    svc._on_event(_evt("left ctrl", "down"))
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    svc._ptt_commit()
    assert calls["start"] == 0                # Ctrl is an extra modifier


def test_stale_tracked_key_does_not_block(monkeypatch):
    """A phantom left in the tracked set by a missed key-up must not stop a clean
    press from firing — the regression that killed the hotkey until a restart."""
    svc, calls, held = _make(monkeypatch)
    svc._down.add("shift")                     # ghost from a dropped key-up
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    svc._ptt_commit()
    assert calls["start"] == 1


def test_extra_key_during_window_cancels(monkeypatch):
    """Win+Shift+T (e.g. PowerToys) must NOT start recording — a key joining the
    combo within the chord window means it's a bigger shortcut, not dictation."""
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    svc._on_event(_evt("t", "down"))           # extra key within the window
    svc._ptt_commit()
    assert calls["start"] == 0                 # canceled


def test_extra_key_after_recording_keeps_recording(monkeypatch):
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    svc._ptt_commit()
    assert calls["start"] == 1
    svc._on_event(_evt("t", "down"))           # extra key AFTER recording began
    assert calls["stop"] == 0                  # keeps recording
    held.discard("win")
    svc._on_event(_evt("left windows", "up"))  # drop a combo key
    svc._ptt_release_check()                    # release grace elapses, combo still not held
    assert calls["stop"] == 1


def test_transient_release_blip_keeps_recording(monkeypatch):
    """A momentary false 'released' reading must NOT end the recording: if the combo
    is physically held again by the time the grace re-check runs, keep going."""
    svc, calls, held = _make(monkeypatch)
    held |= {"win", "shift"}
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    svc._ptt_commit()
    assert calls["start"] == 1
    held.discard("shift")                      # a blip: shift momentarily reads up
    svc._on_event(_evt("left shift", "up"))    # arms the release re-check
    assert calls["stop"] == 0                  # not stopped yet — grace pending
    held.add("shift")                          # combo held again before the re-check
    svc._ptt_release_check()
    assert calls["stop"] == 0                  # blip ignored — still recording


def _make_toggle(monkeypatch, clock):
    s = Settings(hotkeys=HotkeySettings(push_to_talk="windows+shift",
                                        hands_free_enabled=True, toggle_key="right ctrl"))
    monkeypatch.setattr(hk_mod, "load_settings", lambda: s)
    monkeypatch.setattr(hk_mod.time, "monotonic", lambda: clock["t"])
    svc = HotkeyService()
    svc.refresh_config()
    fired: list = []
    svc.on_toggle = lambda: fired.append(1)
    svc._dispatch = lambda cb: cb()
    return svc, fired


def test_doubled_event_does_not_read_as_double_tap(monkeypatch):
    clock = {"t": 100.0}
    svc, fired = _make_toggle(monkeypatch, clock)
    # A doubled hook delivers the SAME right-ctrl down twice at ~the same instant.
    svc._on_event(_evt("right ctrl", "down"))
    svc._on_event(_evt("right ctrl", "down"))
    assert fired == []                          # deduped — not a real double-tap


def test_double_tap_no_longer_fires(monkeypatch):
    """Hands-free was removed from the app, so a double-tap must do nothing even
    when the stored settings still have hands_free_enabled=True."""
    clock = {"t": 100.0}
    svc, fired = _make_toggle(monkeypatch, clock)
    svc._on_event(_evt("right ctrl", "down"))
    clock["t"] += 0.002
    svc._on_event(_evt("right ctrl", "up"))
    clock["t"] += 0.150                          # second tap 150 ms later
    svc._on_event(_evt("right ctrl", "down"))
    assert fired == []                           # hands-free disabled -> no toggle


def test_canary_probes_when_keyboard_recently_active():
    svc = HotkeyService()
    svc._last_real_input = 100.0
    assert svc._skip_probe_when_idle(now=105.0) is False   # 5s idle — keep probing


def test_canary_suppressed_when_user_is_idle():
    svc = HotkeyService()
    svc._last_real_input = 100.0
    svc._os_idle_seconds = lambda: 999.0                   # OS idle too
    assert svc._skip_probe_when_idle(now=131.0) is True    # crossed cutoff — suspend
    assert svc._skip_probe_when_idle(now=145.0) is True    # still idle — stay suspended


def test_canary_resumes_on_os_input_after_idle():
    svc = HotkeyService()
    svc._last_real_input = 100.0
    svc._os_idle_seconds = lambda: 999.0
    assert svc._skip_probe_when_idle(now=131.0) is True     # suspended at t=131
    svc._os_idle_seconds = lambda: 0.5                      # a mouse move just happened
    assert svc._skip_probe_when_idle(now=140.0) is False    # OS input since suspend — resume


def test_real_key_marks_activity_but_canary_does_not(monkeypatch):
    svc, _, _ = _make(monkeypatch)
    svc._last_real_input = 0.0
    svc._on_event(_evt("a", "down"))
    assert svc._last_real_input > 0.0                       # real key = activity
    svc._last_real_input = 0.0
    svc._on_event(types.SimpleNamespace(name=None, event_type="up"))  # the canary
    assert svc._last_real_input == 0.0                      # canary is NOT activity


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


def test_insert_key_fires_only_while_recording(monkeypatch):
    """The dedicated suppressing insert hook fires the clipboard insert only
    during an active recording, once per press (OS key-repeat must not re-fire
    until the key is released)."""
    svc, calls, held = _make(monkeypatch)
    ins: list = []
    svc.on_clipboard_insert = lambda: ins.append(1)

    svc._on_insert_key(_evt("n", "down"))         # not recording yet
    assert ins == []

    held |= {"win", "shift"}                      # start push-to-talk
    svc._on_event(_evt("left windows", "down"))
    svc._on_event(_evt("left shift", "down"))
    svc._ptt_commit()
    assert svc._ptt_active

    svc._on_insert_key(_evt("n", "down"))         # insert
    svc._on_insert_key(_evt("n", "down"))         # OS key-repeat -> ignored
    assert ins == [1]
    svc._on_insert_key(_evt("n", "up"))
    svc._on_insert_key(_evt("n", "down"))         # deliberate second press
    assert ins == [1, 1]
