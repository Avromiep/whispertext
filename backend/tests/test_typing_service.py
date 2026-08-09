"""inject() must silence the global hotkey hook while it synthesizes input, so
injected keystrokes aren't re-processed by our own low-level keyboard hook
(which throttles injection and garbles the output)."""
from __future__ import annotations

from backend.models.settings import Settings
from backend.services import typing_service as ts_mod
from backend.services.typing_service import typing_service


def _setup(monkeypatch):
    seq: list = []
    monkeypatch.setattr(ts_mod, "load_settings", lambda: Settings())
    monkeypatch.setattr(ts_mod.hotkey_service, "set_paused",
                        lambda p: seq.append(("pause", p)))
    monkeypatch.setattr(ts_mod.TypingService, "_wait_for_modifier_release",
                        staticmethod(lambda *a, **k: None))
    return seq


def test_inject_brackets_typing_with_hook_pause(monkeypatch):
    seq = _setup(monkeypatch)
    monkeypatch.setattr(ts_mod.TypingService, "_type_unicode",
                        staticmethod(lambda text, cps: seq.append(("type", text))))
    method = typing_service.inject("hello world")
    assert method == "keystrokes"
    # Hook is paused before the first keystroke and resumed only after the last.
    assert seq == [("pause", True), ("type", "hello world"), ("pause", False)]


def test_hook_resumed_even_if_typing_fails(monkeypatch):
    seq = _setup(monkeypatch)

    def boom(text, cps):
        raise OSError("SendInput failed")

    monkeypatch.setattr(ts_mod.TypingService, "_type_unicode", staticmethod(boom))
    monkeypatch.setattr(ts_mod.TypingService, "_paste",
                        staticmethod(lambda text, restore: "clipboard"))
    method = typing_service.inject("hello")
    assert method == "clipboard"            # fell back to paste
    assert seq[0] == ("pause", True)
    assert seq[-1] == ("pause", False)      # resumed despite the OSError


def test_empty_text_never_touches_the_hook(monkeypatch):
    seq = _setup(monkeypatch)
    assert typing_service.inject("") == "none"
    assert seq == []                        # no pause churn for a no-op
