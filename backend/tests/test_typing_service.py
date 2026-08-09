"""Text injection: 'auto' pastes (atomic, reliable); the opt-in keystroke path
must silence the global hotkey hook while it synthesizes input, so injected
keystrokes aren't re-processed by our own low-level keyboard hook."""
from __future__ import annotations

from backend.models.settings import Settings, TypingSettings
from backend.services import typing_service as ts_mod
from backend.services.typing_service import typing_service


def _setup(monkeypatch, method="auto"):
    seq: list = []
    monkeypatch.setattr(ts_mod, "load_settings",
                        lambda: Settings(typing=TypingSettings(method=method)))
    monkeypatch.setattr(ts_mod.hotkey_service, "set_paused",
                        lambda p: seq.append(("pause", p)))
    monkeypatch.setattr(ts_mod.TypingService, "_wait_for_modifier_release",
                        staticmethod(lambda *a, **k: None))
    return seq


def test_auto_pastes_and_never_types_char_by_char(monkeypatch):
    seq = _setup(monkeypatch, method="auto")
    monkeypatch.setattr(ts_mod.TypingService, "_type_unicode",
                        staticmethod(lambda *a, **k: seq.append(("type", "SHOULD-NOT-RUN"))))
    monkeypatch.setattr(ts_mod.TypingService, "_paste",
                        staticmethod(lambda text, restore: seq.append(("paste", text)) or "clipboard"))
    text = "Testing now to see if it works any better than before."
    assert typing_service.inject(text) == "clipboard"
    # Paste, not per-character injection — and still bracketed by the hook pause.
    assert seq == [("pause", True), ("paste", text), ("pause", False)]


def test_keystrokes_are_bracketed_by_hook_pause(monkeypatch):
    seq = _setup(monkeypatch, method="keystrokes")
    monkeypatch.setattr(ts_mod.TypingService, "_type_unicode",
                        staticmethod(lambda text, cps: seq.append(("type", text))))
    assert typing_service.inject("hello world") == "keystrokes"
    assert seq == [("pause", True), ("type", "hello world"), ("pause", False)]


def test_hook_resumed_even_if_keystrokes_fail(monkeypatch):
    seq = _setup(monkeypatch, method="keystrokes")

    def boom(text, cps):
        raise OSError("SendInput failed")

    monkeypatch.setattr(ts_mod.TypingService, "_type_unicode", staticmethod(boom))
    monkeypatch.setattr(ts_mod.TypingService, "_paste",
                        staticmethod(lambda text, restore: "clipboard"))
    assert typing_service.inject("hello") == "clipboard"   # fell back to paste
    assert seq[0] == ("pause", True)
    assert seq[-1] == ("pause", False)                     # resumed despite the OSError


def test_empty_text_never_touches_the_hook(monkeypatch):
    seq = _setup(monkeypatch)
    assert typing_service.inject("") == "none"
    assert seq == []                                       # no pause churn for a no-op
