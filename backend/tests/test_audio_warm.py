"""The mic stream is kept warm between dictations so recording starts instantly
(a cold device open costs 0.2-1.3s and clips the first words)."""
from __future__ import annotations

import numpy as np

from backend.models.settings import AudioSettings, Settings
from backend.services import audio_service as as_mod
from backend.services.audio_service import AudioService


def _block(n: int = 480, val: int = 1000) -> np.ndarray:
    """One fake capture block: mono int16, shape (frames, 1)."""
    return np.full((n, 1), val, dtype=np.int16)


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


def test_prewarm_opens_and_preroll_is_prepended(monkeypatch):
    svc, created = _setup(monkeypatch, keep_warm=True)
    svc.prewarm()                                         # open the mic on key-down
    assert len(created) == 1 and created[0].active
    # Blocks captured while idle (not yet recording) fill the pre-roll ring.
    for _ in range(5):
        svc._audio_callback(_block(), 480, None, None)
    assert len(svc._preroll) == 5
    svc.start()
    assert len(created) == 1                              # reused the prewarmed stream
    assert len(svc._chunks) == 5                          # pre-roll prepended, not clipped
    svc.stop()
    svc._cancel_idle_timer_locked()


def test_live_sink_receives_preroll_backlog(monkeypatch):
    svc, created = _setup(monkeypatch, keep_warm=True)
    svc.prewarm()
    for _ in range(3):
        svc._audio_callback(_block(), 480, None, None)
    svc.start()                                           # _chunks seeded with 3 pre-roll blocks
    got: list[bytes] = []
    svc.set_chunk_sink(lambda b: got.append(b))
    # The onset already captured is flushed to the live engine as one backlog
    # chunk: 3 blocks x 480 samples x 2 bytes (int16).
    assert got and len(got[0]) == 3 * 480 * 2
    svc.stop()
    svc._cancel_idle_timer_locked()


def test_preroll_capped_to_recent_audio(monkeypatch):
    svc, _ = _setup(monkeypatch, keep_warm=True)
    svc.prewarm()
    for _ in range(as_mod._PREROLL_BLOCKS + 20):          # overflow the ring
        svc._audio_callback(_block(), 480, None, None)
    assert len(svc._preroll) == as_mod._PREROLL_BLOCKS    # only the most recent kept
    svc._close_stream_locked()
    assert len(svc._preroll) == 0                         # cleared on close
