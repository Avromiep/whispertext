"""The mic stream is kept warm between dictations so recording starts instantly
(a cold device open costs 0.2-1.3s and clips the first words)."""
from __future__ import annotations

from backend.models.settings import AudioSettings, Settings
from backend.services import audio_service as as_mod
from backend.services.audio_service import AudioService


class _FakeStream:
    def __init__(self, **kw):
        self.active = False
        self.closed = 0

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.closed += 1
        self.active = False


def _setup(monkeypatch, keep_warm=True):
    created: list[_FakeStream] = []

    def fake_input_stream(**kw):
        s = _FakeStream(**kw)
        created.append(s)
        return s

    monkeypatch.setattr(as_mod.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(as_mod.sd, "query_devices", lambda *a, **k: {"default_samplerate": 48000.0})
    monkeypatch.setattr(as_mod, "load_settings",
                        lambda: Settings(audio=AudioSettings(keep_mic_warm=keep_warm)))
    svc = AudioService()
    return svc, created


def test_warm_stream_reused_across_recordings(monkeypatch):
    svc, created = _setup(monkeypatch, keep_warm=True)
    svc.start()
    assert len(created) == 1 and created[0].active
    svc.stop()
    assert created[0].active and created[0].closed == 0   # kept warm, not closed
    svc.start()
    assert len(created) == 1                              # reused — no cold reopen
    svc.stop()
    svc._cancel_idle_timer_locked()                       # tidy up the daemon timer


def test_open_on_demand_when_warm_disabled(monkeypatch):
    svc, created = _setup(monkeypatch, keep_warm=False)
    svc.start()
    svc.stop()
    assert created[0].closed == 1                         # released immediately
    svc.start()
    assert len(created) == 2                              # reopened for the next one
    svc.stop()
