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


def test_stop_leaves_stream_open_when_warm(monkeypatch):
    # With keep_mic_warm on, stopping must NOT close the stream — the keep-alive
    # holds it warm continuously so the next dictation isn't a cold open.
    svc, created = _setup(monkeypatch, keep_warm=True)
    svc.start()
    svc._chunks = [_block(16000, 300)]                    # a real (non-silent) capture
    svc._started_at = svc._started_at - 1                 # ~1s held
    svc.stop()
    assert created[0].active and created[0].closed == 0   # left open, not released


def test_keepalive_reopens_dead_stream(monkeypatch):
    svc, created = _setup(monkeypatch, keep_warm=True)
    svc.prewarm()                                         # open a warm stream
    assert created[0].active
    created[0].active = False                             # driver silently killed it
    assert svc._keepalive_tick() == "reopened"            # watchdog reopens it
    assert len(created) == 2 and created[1].active
    assert svc._keepalive_tick() == "idle"                # healthy stream left alone
    assert len(created) == 2


def test_keepalive_noop_when_warm_disabled(monkeypatch):
    svc, created = _setup(monkeypatch, keep_warm=False)
    assert svc._keepalive_tick() == "released"            # on-demand: nothing to hold
    assert len(created) == 0


def test_keepalive_skips_during_recording(monkeypatch):
    svc, created = _setup(monkeypatch, keep_warm=True)
    svc.start()                                           # a dictation owns the stream
    created[0].active = False
    assert svc._keepalive_tick() == "idle"                # don't touch it mid-dictation
    assert len(created) == 1


def test_keepalive_releases_mic_when_warm_turned_off(monkeypatch):
    # #3: turning "Keep microphone ready" off releases the mic on the next tick,
    # not only after the next dictation.
    svc, created = _setup(monkeypatch, keep_warm=False)
    svc.prewarm()                                         # a stream is open
    assert created[0].active
    assert svc._keepalive_tick() == "released"
    assert created[0].closed == 1                         # closed right away


def test_keepalive_releases_mic_when_user_paused(monkeypatch):
    # #2: a user pause (tray Pause) releases the mic; a healthy resume reopens it.
    # The transient typing-injection pause (set_paused) must NOT release it.
    from backend.services.hotkey_service import hotkey_service as hs
    svc, created = _setup(monkeypatch, keep_warm=True)
    svc.prewarm()
    assert created[0].active

    monkeypatch.setattr(hs, "_user_paused", True)         # user paused dictation
    assert svc._keepalive_tick() == "released"
    assert created[0].closed == 1                         # mic released while paused

    monkeypatch.setattr(hs, "_user_paused", False)        # resumed
    assert svc._keepalive_tick() == "reopened"
    assert len(created) == 2 and created[1].active

    # A transient typing pause is not a user pause — mic stays held.
    hs.set_paused(True)
    try:
        assert svc._keepalive_tick() == "idle"
        assert created[1].active and created[1].closed == 0
    finally:
        hs.set_paused(False)


def test_keepalive_no_reinit_and_raises_on_failed_open(monkeypatch):
    # #1: a failed keep-alive open must NOT run the PortAudio reinit; it raises so
    # the loop can back off instead of reinitializing every couple of seconds.
    import pytest
    from backend.models.settings import AudioSettings, Settings
    monkeypatch.setattr(as_mod.sd, "query_devices", lambda *a, **k: {"default_samplerate": 48000.0})
    monkeypatch.setattr(as_mod.sd, "InputStream",
                        lambda **kw: (_ for _ in ()).throw(as_mod.sd.PortAudioError("no device")))
    monkeypatch.setattr(as_mod, "load_settings",
                        lambda: Settings(audio=AudioSettings(keep_mic_warm=True)))
    svc = AudioService()
    reinit = {"n": 0}
    monkeypatch.setattr(svc, "_reinit_audio_locked",
                        lambda: reinit.__setitem__("n", reinit["n"] + 1))
    with pytest.raises(RuntimeError):
        svc._keepalive_tick()
    assert reinit["n"] == 0                               # never reinitialized PortAudio


def test_keepalive_backoff_schedule():
    assert [as_mod._keepalive_backoff(n) for n in (1, 2, 3, 4, 5, 10)] \
        == [2.0, 5.0, 15.0, 60.0, 60.0, 60.0]
