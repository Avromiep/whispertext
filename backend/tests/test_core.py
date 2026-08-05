"""Unit tests for WhisperText core services (no audio hardware / network needed)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from backend.models.settings import Settings
from backend.services.audio_service import (AudioService, audio_service,
                                            speech_seconds)
from backend.services.llm_service import (PROMPT_PRESETS, PROVIDER_CLASSES,
                                          LLMService)
from backend.services.pipeline import MIN_FILLER_SPEECH_S, pipeline
from backend.storage.database import HistoryStore
from backend.utils.retry import retry_async
from backend.utils.hardware import recommend_local_models
from backend.utils.text import (apply_vocabulary_casing, build_vocabulary_prompt,
                                 is_silence_hallucination)


# ------------------------------------------------------------------- settings
class TestSettings:
    def test_defaults_match_spec(self):
        s = Settings()
        assert s.hotkeys.push_to_talk == "windows+shift"
        assert s.hotkeys.toggle_key == "right ctrl"
        assert s.whisper.model == "small"
        assert s.general.theme == "light"  # the tan palette matching the overlay

    def test_deep_merge_preserves_siblings(self, tmp_path, monkeypatch):
        import backend.models.settings as ms
        monkeypatch.setattr(ms, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(ms, "_settings", None)
        updated = ms.update_settings({"ai": {"provider": "gemini"}})
        assert updated.ai.provider == "gemini"
        assert updated.ai.enabled is False          # sibling untouched
        assert updated.hotkeys.push_to_talk == "windows+shift"
        # survives reload
        monkeypatch.setattr(ms, "_settings", None)
        assert ms.load_settings().ai.provider == "gemini"

    def test_write_keeps_recoverable_backup(self, tmp_path, monkeypatch):
        """Every save snapshots the previous file, so an accidental wipe (like
        clearing the vocabulary) can be recovered from the backups folder."""
        import backend.models.settings as ms
        monkeypatch.setattr(ms, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(ms, "SETTINGS_BACKUP_DIR", tmp_path / "backups")
        monkeypatch.setattr(ms, "_settings", None)
        monkeypatch.setattr(ms, "_loaded_mtime", None)

        ms.update_settings({"vocabulary": {"words": ["GitHub", "OAuth"]}})
        ms.update_settings({"vocabulary": {"words": []}})    # accidental wipe

        backups = sorted((tmp_path / "backups").glob("settings-*.json"))
        assert backups, "no backup was written"
        recovered = [json.loads(b.read_text(encoding="utf-8"))["vocabulary"]["words"]
                     for b in backups]
        assert ["GitHub", "OAuth"] in recovered   # the pre-wipe words survive

    def test_save_does_not_clobber_external_disk_write(self, tmp_path, monkeypatch):
        """A save must merge onto the freshest file, not a stale in-memory
        cache — the bug that wiped custom vocabulary when a second backend
        process held older settings."""
        import backend.models.settings as ms
        monkeypatch.setattr(ms, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(ms, "_settings", None)
        monkeypatch.setattr(ms, "_loaded_mtime", None)

        # This process caches settings with an empty vocabulary.
        assert ms.load_settings().vocabulary.words == []

        # Another process writes vocabulary words straight to the file.
        data = ms.Settings().model_dump()
        data["vocabulary"]["words"] = ["GitHub", "OAuth"]
        time.sleep(0.02)  # ensure a distinct mtime so the change is detected
        (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")

        # A later, unrelated change from the stale-cache process must keep them.
        updated = ms.update_settings({"general": {"theme": "dark"}})
        assert updated.vocabulary.words == ["GitHub", "OAuth"]
        assert updated.general.theme == "dark"


# -------------------------------------------------------------------- history
class TestHistory:
    def test_crud_and_stats(self, tmp_path):
        store = HistoryStore(tmp_path / "t.db")
        eid = store.add(app="Notepad", raw="uh hello", final="Hello.",
                        duration_s=1.2, provider="openai", language="en")
        assert eid > 0
        rows = store.list()
        assert rows[0]["final_text"] == "Hello."
        store.set_favorite(eid, True)
        assert store.list()[0]["favorite"] == 1
        assert store.stats()["total"] == 1
        store.delete(eid)
        assert store.stats()["total"] == 0

    def test_search_and_purge(self, tmp_path):
        store = HistoryStore(tmp_path / "t.db")
        store.add(app="Word", raw="alpha", final="Alpha.", duration_s=1,
                  provider="x", language="en")
        store.add(app="Slack", raw="beta", final="Beta.", duration_s=1,
                  provider="x", language="en")
        assert len(store.list(search="Slack")) == 1
        assert store.purge_older_than(30) == 0     # nothing old enough


# ---------------------------------------------------------------------- retry
class TestRetry:
    def test_succeeds_after_failures(self, monkeypatch):
        import backend.utils.retry as r
        monkeypatch.setattr(r, "BACKOFF_SCHEDULE", (0.01, 0.01, 0.01))
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("boom")
            return "ok"

        assert asyncio.run(retry_async(flaky, attempts=3)) == "ok"
        assert calls["n"] == 3

    def test_raises_after_exhaustion(self, monkeypatch):
        import backend.utils.retry as r
        monkeypatch.setattr(r, "BACKOFF_SCHEDULE", (0.01,))

        async def always_fails():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            asyncio.run(retry_async(always_fails, attempts=2))


# ------------------------------------------------------------------------- ai
class TestLLM:
    def test_all_spec_presets_exist(self):
        for preset in ("professional", "friendly", "executive", "technical",
                       "medical", "legal", "academic", "creative"):
            assert preset in PROMPT_PRESETS

    def test_all_spec_providers_registered(self):
        for pid in ("openai", "anthropic", "gemini", "openrouter", "ollama",
                    "lmstudio", "custom"):
            assert pid in PROVIDER_CLASSES

    def test_provider_chain_hybrid_dedupes(self, monkeypatch):
        import backend.services.llm_service as m
        monkeypatch.setattr(m, "has_api_key", lambda _pid: True)
        s = Settings()
        s.ai.mode = "hybrid"
        s.ai.provider = "openai"
        chain = LLMService()._provider_chain(s)
        assert chain[0] == "openai"
        assert len(chain) == len(set(chain))

    def test_offline_only_filters_cloud(self):
        s = Settings()
        s.ai.mode = "hybrid"
        s.ai.offline_only = True
        chain = LLMService()._provider_chain(s)
        assert all(PROVIDER_CLASSES[p].is_local for p in chain)

    def test_minimize_costs_prefers_local(self):
        s = Settings()
        s.ai.mode = "hybrid"
        s.ai.provider = "openai"
        s.ai.minimize_costs = True
        chain = LLMService()._provider_chain(s)
        assert PROVIDER_CLASSES[chain[0]].is_local

    def test_chain_skips_cloud_providers_without_keys(self, monkeypatch):
        import backend.services.llm_service as m
        monkeypatch.setattr(m, "has_api_key", lambda pid: pid == "gemini")
        s = Settings()
        s.ai.mode = "hybrid"
        s.ai.provider = "gemini"
        chain = LLMService()._provider_chain(s)
        assert "openai" not in chain and "openrouter" not in chain
        assert chain[0] == "gemini"
        assert "ollama" in chain  # local providers never need keys

    def test_transient_error_classification(self):
        import httpx
        from backend.services.llm_service import _is_transient

        def status_error(code):
            return httpx.HTTPStatusError(
                "err", request=httpx.Request("GET", "http://x"),
                response=httpx.Response(code, request=httpx.Request("GET", "http://x")))

        assert not _is_transient(status_error(401))   # bad key: fail fast
        assert not _is_transient(status_error(404))
        assert _is_transient(status_error(429))       # rate limit: retry
        assert _is_transient(status_error(503))
        assert not _is_transient(httpx.ConnectError("refused"))  # server down
        assert _is_transient(httpx.ReadTimeout("slow"))

    def test_retry_respects_should_retry_predicate(self, monkeypatch):
        import backend.utils.retry as r
        monkeypatch.setattr(r, "BACKOFF_SCHEDULE", (0.01,))
        calls = {"n": 0}

        async def fails_permanently():
            calls["n"] += 1
            raise ValueError("permanent")

        with pytest.raises(ValueError):
            asyncio.run(retry_async(fails_permanently, attempts=3,
                                    should_retry=lambda _: False))
        assert calls["n"] == 1  # no pointless retries

    def test_cleanup_returns_raw_when_disabled(self):
        s = Settings()
        s.ai.enabled = False
        import backend.services.llm_service as m
        import backend.models.settings as ms
        orig = ms._settings
        ms._settings = s
        try:
            res = asyncio.run(m.llm_service.cleanup("raw text here"))
            assert res.text == "raw text here"
        finally:
            ms._settings = orig


# ---------------------------------------------------------------------- audio
class TestAudioProcessing:
    def test_trim_silence_keeps_speech(self):
        rate = 16000
        silence = np.zeros(rate, dtype=np.float32)
        speech = (np.random.default_rng(0).standard_normal(rate) * 0.3).astype(np.float32)
        audio = np.concatenate([silence, speech, silence])
        trimmed = AudioService._trim_silence(audio, rate)
        assert trimmed.size < audio.size
        assert trimmed.size >= speech.size          # speech fully retained

    def test_trim_all_silence_returns_original(self):
        audio = np.zeros(16000, dtype=np.float32)
        assert AudioService._trim_silence(audio, 16000).size == audio.size


# ------------------------------------------------------- silence hallucination
class TestSilenceRejection:
    """Handed silence, Whisper invents a filler ("So", "Okay", "Thank you")
    instead of returning nothing, so silence must never reach an engine —
    least of all Groq, which has no voice-activity filter of its own.

    Loudness cannot make this call: on a noisy input the noise floor and quiet
    speech overlap (measured 0.0113 vs 0.0126 peak frame RMS on one machine),
    so these tests exercise the real Silero detector against real speech.
    """

    RATE = 16000
    FIXTURES = Path(__file__).parent / "fixtures"

    @staticmethod
    def _pcm(signal):
        return (np.clip(signal, -1, 1) * 32767).astype(np.int16)

    @classmethod
    def _load(cls, name):
        with wave.open(str(cls.FIXTURES / name), "rb") as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        audio = pcm.astype(np.float32) / 32768.0
        return audio / max(float(np.max(np.abs(audio))), 1e-9)

    @classmethod
    def _noise(cls, seconds, level=0.0113, seed=0):
        """Room tone at a realistic noise-floor level for a live microphone."""
        rng = np.random.default_rng(seed)
        n = int(cls.RATE * seconds)
        t = np.linspace(0, seconds, n, endpoint=False)
        tone = rng.normal(0, level / 3, n)
        tone += 0.4 * level * np.sin(2 * np.pi * 60 * t)      # mains hum
        return tone.astype(np.float32)

    @classmethod
    def _spoken(cls, name="speech_sentence_16k.wav", peak=0.15, pad_s=1.0):
        """Real speech at `peak`, laid into room tone with lead-in and lead-out."""
        clip = cls._load(name) * peak
        n = clip.size + int(cls.RATE * pad_s * 2)
        audio = cls._noise(n / cls.RATE, seed=4)[:n].copy()
        start = int(cls.RATE * pad_s)
        audio[start:start + clip.size] += clip
        return np.clip(audio, -1, 1).astype(np.float32)

    # -- the gate ------------------------------------------------------------
    def test_room_tone_is_discarded(self):
        assert audio_service._post_process(self._pcm(self._noise(3))).size == 0

    def test_digital_silence_is_discarded(self):
        assert audio_service._post_process(self._pcm(np.zeros(self.RATE * 2))).size == 0

    def test_loud_room_tone_is_still_discarded(self):
        """A noisy mic must not buy its way past the gate on level alone."""
        assert audio_service._post_process(self._pcm(self._noise(3, level=0.03))).size == 0

    @pytest.mark.parametrize("peak", [0.02, 0.05, 0.15, 0.5])
    def test_speech_survives_at_every_volume(self, peak):
        assert audio_service._post_process(self._pcm(self._spoken(peak=peak))).size > 0

    def test_single_word_survives(self):
        audio = self._spoken("speech_word_16k.wav", peak=0.15)
        assert audio_service._post_process(self._pcm(audio)).size > 0

    def test_auto_gain_never_amplifies_room_tone(self):
        # Auto-gain divides by the peak, so this was previously normalised to
        # 0.9 and handed to the engine as a loud-looking signal.
        assert audio_service._post_process(self._pcm(self._noise(2, seed=1))).size == 0

    def test_speech_seconds_measures_only_speech(self):
        assert speech_seconds(self._noise(3), self.RATE) == 0.0
        assert speech_seconds(self._spoken(), self.RATE) > 1.0

    # -- the filler fallback behind it ---------------------------------------
    @pytest.mark.parametrize("text", ["Okay.", "So", "so", "you", "Thank you.", "Bye!"])
    def test_known_fillers_detected(self, text):
        assert is_silence_hallucination(text)

    @pytest.mark.parametrize("text", ["Okay, let's ship it.", "So I went home",
                                      "Send the report to Dave", "No thanks, I'm good"])
    def test_real_sentences_are_not_fillers(self, text):
        assert not is_silence_hallucination(text)

    def test_spoken_filler_is_kept_but_silent_one_is_dropped(self):
        """Speech duration, not loudness, is what makes the blocklist safe."""
        spoken = self._spoken("speech_word_16k.wav", peak=0.15)
        assert pipeline._is_hallucination("Okay.", spoken) is False
        assert pipeline._is_hallucination("Thank you.", self._noise(3)) is True

    def test_deliberate_one_word_clears_the_bound_with_margin(self):
        spoken = self._spoken("speech_word_16k.wav", peak=0.15)
        assert speech_seconds(spoken, self.RATE) > MIN_FILLER_SPEECH_S * 1.2

    def test_real_sentence_kept_even_when_quiet(self):
        assert pipeline._is_hallucination(
            "Send the report to Dave", self._spoken(peak=0.02)) is False


# ------------------------------------------------------------------- hands-free
class _ScriptedMic:
    """A stand-in AudioService that plays back a scripted sequence of audio
    blocks, so the hands-free endpoint monitor can be driven deterministically
    without a real microphone."""

    RATE = 16000

    def __init__(self, segments):
        # segments: list of (seconds, float32 source | None for room tone)
        self._segments = segments
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self.finished = threading.Event()
        rng = np.random.default_rng(0)
        self._room = (rng.normal(0, 0.0113 / 3, self.RATE).astype(np.float32))

    @property
    def is_recording(self):
        return self._recording

    def start(self):
        self._chunks = []
        self._recording = True
        threading.Thread(target=self._feed, daemon=True).start()

    def _feed(self):
        block = int(self.RATE * 0.03)
        for seconds, src in self._segments:
            for i in range(int(seconds / 0.03)):
                if not self._recording:
                    return
                pool = self._room if src is None else src
                off = (i * block) % max(1, pool.size - block)
                chunk = (pool[off:off + block] * 32767).astype(np.int16)
                self._chunks.append(chunk.reshape(-1, 1))
                time.sleep(0.03)

    def tail_audio(self, seconds):
        from backend.services.audio_service import AudioService
        return AudioService.tail_audio(self, seconds)

    def stop(self):
        self._recording = False
        self.finished.set()
        return np.zeros(0, dtype=np.float32)


class TestHandsFree:
    RATE = 16000
    FIXTURES = Path(__file__).parent / "fixtures"

    def _speech(self, peak=0.3):
        with wave.open(str(self.FIXTURES / "speech_sentence_16k.wav"), "rb") as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        a = pcm.astype(np.float32) / 32768.0
        return a / max(float(np.max(np.abs(a))), 1e-9) * peak

    def test_tail_audio_returns_recent_window(self):
        from backend.services.audio_service import AudioService
        svc = AudioService()
        block = int(self.RATE * 0.03)
        # 3 s of ascending ramps so we can tell early blocks from late ones.
        svc._chunks = [np.full((block, 1), i, dtype=np.int16) for i in range(100)]
        tail = svc.tail_audio(1.0)
        assert abs(tail.size - self.RATE) <= block          # ~1 s, not all 3 s
        assert tail[-1] > tail[0]                            # keeps the latest audio

    @pytest.mark.parametrize("segments,lo,hi", [
        # Speak ~2.6 s, then a 2 s pause (default silence_ms) -> stop shortly after.
        ("speak_then_pause", 3.8, 6.5),
        # Never speak -> the no-speech timeout (~4 s) ends it instead of forever.
        ("never_speak", 3.5, 5.5),
    ])
    def test_auto_stops(self, segments, lo, hi, monkeypatch):
        script = ([(2.6, self._speech()), (4.0, None)] if segments == "speak_then_pause"
                  else [(8.0, None)])
        mic = _ScriptedMic(script)
        import backend.services.pipeline as pl
        monkeypatch.setattr(pl, "audio_service", mic)

        t0 = time.monotonic()
        pl.pipeline.toggle()                 # begin hands-free
        assert mic.finished.wait(timeout=12), "endpoint monitor never stopped"
        elapsed = time.monotonic() - t0
        assert lo <= elapsed <= hi, f"stopped at {elapsed:.1f}s, want {lo}-{hi}s"

    def test_manual_double_tap_still_stops_immediately(self, monkeypatch):
        mic = _ScriptedMic([(10.0, None)])
        import backend.services.pipeline as pl
        monkeypatch.setattr(pl, "audio_service", mic)
        pl.pipeline.toggle()                 # start
        time.sleep(0.5)
        assert mic.is_recording
        pl.pipeline.toggle()                 # manual stop
        assert mic.finished.wait(timeout=2)

    def test_no_speech_uses_overlay_pill_not_notification(self, monkeypatch):
        """The 'no speech' feedback must ride the overlay status pill, not a
        desktop notification that slides in from the screen corner."""
        import backend.services.pipeline as pl
        calls = []
        monkeypatch.setattr(pl.bus, "status", lambda state, **k: calls.append(("status", state)))
        monkeypatch.setattr(pl.bus, "notify", lambda *a, **k: calls.append(("notify", a)))
        pl.pipeline._report_no_speech()
        assert ("status", "empty") in calls
        assert not any(c[0] == "notify" for c in calls)


# ------------------------------------------------------------------ vocabulary
class TestVocabulary:
    WORDS = ["GitHub", "OAuth", "kubectl", "New York", "C++"]

    def test_prompt_joins_terms(self):
        assert build_vocabulary_prompt(self.WORDS) == "GitHub, OAuth, kubectl, New York, C++"

    def test_prompt_empty_is_none(self):
        assert build_vocabulary_prompt([]) is None
        assert build_vocabulary_prompt(["  ", ""]) is None

    @pytest.mark.parametrize("text,expected", [
        ("i pushed to github today", "i pushed to GitHub today"),
        ("set up oauth for the app", "set up OAuth for the app"),
        ("run Kubectl get pods", "run kubectl get pods"),   # wrong casing corrected
        ("i love new york city", "i love New York city"),
        ("learning c++ is fun", "learning C++ is fun"),
        ("GITHUB is down", "GitHub is down"),
    ])
    def test_casing_enforced(self, text, expected):
        assert apply_vocabulary_casing(text, self.WORDS) == expected

    def test_possessive_and_punctuation(self):
        assert apply_vocabulary_casing("github's api, then github.", ["GitHub"]) \
            == "GitHub's api, then GitHub."

    @pytest.mark.parametrize("text", ["yorkshire pudding", "scoauth", "githubbing"])
    def test_no_substring_false_positives(self, text):
        # A vocab term must not fire inside a longer word.
        assert apply_vocabulary_casing(text, self.WORDS) == text

    def test_longer_phrase_wins(self):
        # "New York" should be applied whole, not leave a stray "York".
        assert apply_vocabulary_casing("new york", ["York", "New York"]) == "New York"

    def test_empty_vocabulary_is_noop(self):
        assert apply_vocabulary_casing("nothing changes here", []) == "nothing changes here"


# ---------------------------------------------------------- capture-drop detect
class TestCaptureDropDetection:
    """When the mic delivers far less audio than the key was held for, the
    recording is cut off — it must be flagged (and logged) so a silent cut-off
    becomes a visible warning."""

    RATE = 16000

    def _svc(self, monkeypatch):
        from backend.services.audio_service import AudioService
        svc = AudioService()
        # Bypass VAD/gain post-processing — we're testing the capture stats.
        monkeypatch.setattr(svc, "_post_process", lambda pcm: pcm.astype(np.float32))
        svc._recording = True
        svc._stream = None
        svc._overflows = 0
        return svc

    def test_total_drop_flagged(self, monkeypatch):
        svc = self._svc(monkeypatch)
        svc._chunks = []                              # mic delivered nothing
        svc._started_at = time.monotonic() - 20       # but key held ~20s
        svc.stop()
        cap = svc.last_capture
        assert cap["dropped"] is True
        assert cap["held_s"] >= 19 and cap["audio_s"] == 0.0

    def test_partial_drop_flagged(self, monkeypatch):
        svc = self._svc(monkeypatch)
        svc._chunks = [np.zeros((2 * self.RATE, 1), dtype=np.int16)]  # only 2s captured
        svc._started_at = time.monotonic() - 19                        # held ~19s
        svc.stop()
        assert svc.last_capture["dropped"] is True
        assert 15 <= svc.last_capture["dropped_s"] <= 18

    def test_normal_capture_not_flagged(self, monkeypatch):
        svc = self._svc(monkeypatch)
        svc._chunks = [np.zeros((5 * self.RATE, 1), dtype=np.int16)]  # 5s captured
        svc._started_at = time.monotonic() - 5                         # held ~5s
        svc.stop()
        assert svc.last_capture["dropped"] is False
        assert svc.last_capture["dropped_s"] < 1.0


# --------------------------------------------------------------------- hotkeys
class TestHotkeys:
    def test_double_tap_detection(self, monkeypatch):
        from backend.services.hotkey_service import HotkeyService, _norm
        import backend.services.hotkey_service as hm
        # Isolate from real on-disk settings — this test only cares about
        # double-tap detection itself, not the user's actual saved prefs.
        monkeypatch.setattr(hm, "load_settings", lambda: Settings())
        svc = HotkeyService()
        fired = []
        svc.on_toggle = lambda: fired.append(1)

        class Ev:
            def __init__(self, name, etype):
                self.name, self.event_type = name, etype

        svc._on_event(Ev("right ctrl", "down"))
        svc._on_event(Ev("right ctrl", "up"))
        svc._on_event(Ev("right ctrl", "down"))
        time.sleep(0.15)                            # dispatch thread
        assert fired == [1]
        assert _norm("left windows") == "windows"

    def test_ptt_hold_and_release(self, monkeypatch):
        from backend.services.hotkey_service import HotkeyService
        import backend.services.hotkey_service as hm
        monkeypatch.setattr(hm, "load_settings", lambda: Settings())
        svc = HotkeyService()
        events = []
        svc.on_ptt_start = lambda: events.append("start")
        svc.on_ptt_stop = lambda: events.append("stop")

        class Ev:
            def __init__(self, name, etype):
                self.name, self.event_type = name, etype

        svc._on_event(Ev("left windows", "down"))
        svc._on_event(Ev("left shift", "down"))
        svc._on_event(Ev("left shift", "up"))
        time.sleep(0.15)
        assert events == ["start", "stop"]

    def test_double_tap_ignored_when_hands_free_disabled(self, monkeypatch):
        from backend.services.hotkey_service import HotkeyService
        import backend.services.hotkey_service as hm
        s = Settings()
        s.hotkeys.hands_free_enabled = False
        monkeypatch.setattr(hm, "load_settings", lambda: s)
        svc = HotkeyService()
        fired = []
        svc.on_toggle = lambda: fired.append(1)

        class Ev:
            def __init__(self, name, etype):
                self.name, self.event_type = name, etype

        svc._on_event(Ev("right ctrl", "down"))
        svc._on_event(Ev("right ctrl", "up"))
        svc._on_event(Ev("right ctrl", "down"))
        time.sleep(0.15)
        assert fired == []


# ----------------------------------------------------------------------- groq
class TestGroqWhisper:
    def test_encode_wav_round_trips(self):
        import wave
        from backend.services.groq_whisper_service import encode_wav
        rng = np.random.default_rng(0)
        audio = (rng.standard_normal(16000) * 0.3).astype(np.float32)
        wav_bytes = encode_wav(audio)
        import io
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == 16000
            assert w.getnframes() == audio.size

    def test_transcribe_raises_without_key(self, monkeypatch):
        import backend.services.groq_whisper_service as m
        monkeypatch.setattr(m, "get_api_key", lambda _pid: None)
        svc = m.GroqWhisperService()
        with pytest.raises(RuntimeError):
            asyncio.run(svc.transcribe(np.ones(16000, dtype=np.float32)))

    def test_transcribe_empty_audio_short_circuits(self, monkeypatch):
        import backend.services.groq_whisper_service as m
        monkeypatch.setattr(m, "get_api_key", lambda _pid: "fake-key")
        svc = m.GroqWhisperService()
        result = asyncio.run(svc.transcribe(np.zeros(100, dtype=np.float32)))
        assert result.text == ""

    def test_transcribe_parses_response(self, monkeypatch):
        import backend.services.groq_whisper_service as m
        monkeypatch.setattr(m, "get_api_key", lambda _pid: "fake-key")

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"text": "hello world"}

        captured = {}

        class FakeClient:
            async def post(self, url, headers=None, files=None, data=None):
                captured["url"], captured["data"] = url, data
                return FakeResponse()

        svc = m.GroqWhisperService()
        svc._client = FakeClient()
        audio = np.ones(16000, dtype=np.float32) * 0.1
        result = asyncio.run(svc.transcribe(audio, language="en"))
        assert result.text == "hello world"
        assert captured["url"] == m.API_URL
        assert captured["data"]["language"] == "en"

    def test_validate_no_key(self, monkeypatch):
        import backend.services.groq_whisper_service as m
        monkeypatch.setattr(m, "get_api_key", lambda _pid: None)
        svc = m.GroqWhisperService()
        r = asyncio.run(svc.validate())
        assert r["connected"] is False

    def test_transcribe_strips_trailing_ellipsis(self, monkeypatch):
        import backend.services.groq_whisper_service as m
        monkeypatch.setattr(m, "get_api_key", lambda _pid: "fake-key")

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"text": "I'm thinking so..."}

        class FakeClient:
            async def post(self, *a, **kw):
                return FakeResponse()

        svc = m.GroqWhisperService()
        svc._client = FakeClient()
        audio = np.ones(16000, dtype=np.float32) * 0.1
        result = asyncio.run(svc.transcribe(audio, language="en"))
        assert result.text == "I'm thinking so"


class TestTextUtils:
    def test_strips_trailing_ellipsis_variants(self):
        from backend.utils.text import strip_trailing_ellipsis
        assert strip_trailing_ellipsis("I'm thinking so...") == "I'm thinking so"
        assert strip_trailing_ellipsis("I'm thinking so…") == "I'm thinking so"
        assert strip_trailing_ellipsis("I'm thinking so...  ") == "I'm thinking so"

    def test_leaves_normal_sentences_alone(self):
        from backend.utils.text import strip_trailing_ellipsis
        assert strip_trailing_ellipsis("Hello there.") == "Hello there."
        assert strip_trailing_ellipsis("Wait... really?") == "Wait... really?"

    def test_explicit_api_key_overrides_stored_key(self, monkeypatch):
        """The pipeline passes the backup key explicitly; it must win over
        whatever's in keyring for the default 'groq' provider id."""
        import backend.services.groq_whisper_service as m
        monkeypatch.setattr(m, "get_api_key", lambda _pid: "stored-key")

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"text": "ok"}

        captured = {}

        class FakeClient:
            async def post(self, url, headers=None, files=None, data=None):
                captured["auth"] = headers["Authorization"]
                return FakeResponse()

        svc = m.GroqWhisperService()
        svc._client = FakeClient()
        audio = np.ones(16000, dtype=np.float32) * 0.1
        asyncio.run(svc.transcribe(audio, api_key="explicit-backup-key"))
        assert captured["auth"] == "Bearer explicit-backup-key"

    def test_validate_backup_provider_id(self, monkeypatch):
        import backend.services.groq_whisper_service as m
        keys = {"groq": "primary", "groq_backup": "backup"}
        monkeypatch.setattr(m, "get_api_key", lambda pid: keys.get(pid))
        svc = m.GroqWhisperService()
        captured = {}

        class FakeResponse:
            def raise_for_status(self): pass

        class FakeClient:
            async def get(self, url, headers=None):
                captured["auth"] = headers["Authorization"]
                return FakeResponse()

        svc._client = FakeClient()
        asyncio.run(svc.validate(m.BACKUP_PROVIDER_ID))
        assert captured["auth"] == "Bearer backup"


# --------------------------------------------------------------------- gemini
class TestGeminiProvider:
    def test_thinking_disabled_for_25_models(self):
        from backend.models.settings import ProviderConfig
        from backend.services.providers.gemini_provider import GeminiProvider

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

        captured = {}

        class FakeClient:
            async def post(self, url, params=None, json=None):
                captured["json"] = json
                return FakeResponse()

        provider = GeminiProvider(ProviderConfig(model="gemini-2.5-flash"), api_key="x")
        provider._client = FakeClient()
        asyncio.run(provider.generate("sys", "user text"))
        assert captured["json"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}

    def test_thinking_config_omitted_for_older_models(self):
        from backend.models.settings import ProviderConfig
        from backend.services.providers.gemini_provider import GeminiProvider

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

        captured = {}

        class FakeClient:
            async def post(self, url, params=None, json=None):
                captured["json"] = json
                return FakeResponse()

        provider = GeminiProvider(ProviderConfig(model="gemini-1.5-flash"), api_key="x")
        provider._client = FakeClient()
        asyncio.run(provider.generate("sys", "user text"))
        assert "thinkingConfig" not in captured["json"]["generationConfig"]


# ---------------------------------------------------------------------- typing
class TestTypingEngine:
    def test_input_struct_layout(self):
        """SendInput silently injects nothing if sizeof(INPUT) is wrong (x64: 40)."""
        import ctypes
        from backend.services.typing_service import _INPUT
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        assert ctypes.sizeof(_INPUT) == expected

    def test_events_for_char(self):
        from backend.services.typing_service import (
            _events_for_char, KEYEVENTF_UNICODE, VK_RETURN)
        # plain char -> unicode down+up
        ev = _events_for_char("é")
        assert len(ev) == 2
        assert ev[0].union.ki.dwFlags & KEYEVENTF_UNICODE
        assert ev[0].union.ki.wScan == ord("é")
        # newline -> VK_RETURN, not unicode
        ev = _events_for_char("\n")
        assert ev[0].union.ki.wVk == VK_RETURN
        assert not (ev[0].union.ki.dwFlags & KEYEVENTF_UNICODE)
        # emoji (surrogate pair) -> 4 events
        assert len(_events_for_char("🎤")) == 4


# ---------------------------------------------------------------- transcribe
class TestPipelineTranscribeRouting:
    """DictationPipeline._transcribe: engine routing + primary/backup/local fallback chain."""

    def _make_pipeline(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        original_history_store = pm.HistoryStore
        monkeypatch.setattr(pm, "HistoryStore", lambda: original_history_store(tmp_path / "t.db"))
        return pm.DictationPipeline()

    def test_routes_to_local_when_engine_is_local(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        s = Settings()
        s.whisper.engine = "local"
        monkeypatch.setattr(pm, "load_settings", lambda: s)
        called = {"local": False}
        monkeypatch.setattr(pm.whisper_service, "transcribe",
                            lambda audio: called.__setitem__("local", True) or object())
        p = self._make_pipeline(monkeypatch, tmp_path)
        p._transcribe(np.zeros(10, dtype=np.float32))
        assert called["local"]

    def test_routes_to_groq_with_primary_key(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        s = Settings()
        s.whisper.engine = "groq"
        monkeypatch.setattr(pm, "load_settings", lambda: s)
        monkeypatch.setattr(pm.encryption, "get_api_key",
                            lambda pid: "primary-key" if pid == pm.PROVIDER_ID else None)
        sentinel = object()
        used_keys = []

        async def fake_transcribe(audio, language, model, api_key=None, prompt=None):
            used_keys.append(api_key)
            return sentinel

        monkeypatch.setattr(pm.groq_whisper_service, "transcribe", fake_transcribe)
        p = self._make_pipeline(monkeypatch, tmp_path)
        result = p._transcribe(np.zeros(10, dtype=np.float32))
        assert result is sentinel
        assert used_keys == ["primary-key"]

    def test_falls_back_to_backup_key_on_primary_failure(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        s = Settings()
        s.whisper.engine = "groq"
        monkeypatch.setattr(pm, "load_settings", lambda: s)
        keys = {pm.PROVIDER_ID: "primary-key", pm.BACKUP_PROVIDER_ID: "backup-key"}
        monkeypatch.setattr(pm.encryption, "get_api_key", lambda pid: keys.get(pid))
        sentinel = object()
        used_keys = []

        async def fake_transcribe(audio, language, model, api_key=None, prompt=None):
            used_keys.append(api_key)
            if api_key == "primary-key":
                raise RuntimeError("429 rate limit")
            return sentinel

        monkeypatch.setattr(pm.groq_whisper_service, "transcribe", fake_transcribe)
        p = self._make_pipeline(monkeypatch, tmp_path)
        result = p._transcribe(np.zeros(10, dtype=np.float32))
        assert result is sentinel
        assert used_keys == ["primary-key", "backup-key"]

    def test_falls_back_to_local_when_both_groq_keys_fail(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        s = Settings()
        s.whisper.engine = "groq"
        monkeypatch.setattr(pm, "load_settings", lambda: s)
        keys = {pm.PROVIDER_ID: "primary-key", pm.BACKUP_PROVIDER_ID: "backup-key"}
        monkeypatch.setattr(pm.encryption, "get_api_key", lambda pid: keys.get(pid))

        async def failing_transcribe(audio, language, model, api_key=None):
            raise RuntimeError("network down")

        monkeypatch.setattr(pm.groq_whisper_service, "transcribe", failing_transcribe)
        called = {"local": False}
        monkeypatch.setattr(pm.whisper_service, "transcribe",
                            lambda audio: called.__setitem__("local", True) or object())
        p = self._make_pipeline(monkeypatch, tmp_path)
        p._transcribe(np.zeros(10, dtype=np.float32))
        assert called["local"]

    def test_uses_local_when_groq_selected_but_no_key(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        s = Settings()
        s.whisper.engine = "groq"
        monkeypatch.setattr(pm, "load_settings", lambda: s)
        monkeypatch.setattr(pm.encryption, "get_api_key", lambda pid: None)
        called = {"local": False}
        monkeypatch.setattr(pm.whisper_service, "transcribe",
                            lambda audio: called.__setitem__("local", True) or object())
        p = self._make_pipeline(monkeypatch, tmp_path)
        p._transcribe(np.zeros(10, dtype=np.float32))
        assert called["local"]


# ------------------------------------------------------------------ test mode
class TestPipelineTestMode:
    """Onboarding's mic test: real hotkey, but no cleanup/typing/history side effects."""

    def _make_pipeline(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        original_history_store = pm.HistoryStore
        monkeypatch.setattr(pm, "HistoryStore", lambda: original_history_store(tmp_path / "t.db"))
        return pm.DictationPipeline()

    def test_test_mode_publishes_result_and_skips_side_effects(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        from backend.services.whisper_service import TranscriptionResult

        monkeypatch.setattr(pm, "load_settings", lambda: Settings())
        monkeypatch.setattr(pm.whisper_service, "transcribe",
                            lambda audio: TranscriptionResult("hello world", "en", 0.9, 0.1))

        published = []
        monkeypatch.setattr(pm.bus, "publish", lambda t, d=None: published.append((t, d)))

        cleanup_called = {"v": False}
        typing_called = {"v": False}
        monkeypatch.setattr(pm.llm_service, "cleanup",
                            lambda text: cleanup_called.__setitem__("v", True))
        monkeypatch.setattr(pm.typing_service, "inject",
                            lambda text: typing_called.__setitem__("v", True))

        p = self._make_pipeline(monkeypatch, tmp_path)
        p.set_test_mode(True)
        p._process(np.ones(16000, dtype=np.float32) * 0.1)

        assert cleanup_called["v"] is False
        assert typing_called["v"] is False
        assert p.history.stats()["total"] == 0
        result_events = [d for t, d in published if t == "test_result"]
        assert result_events == [{"text": "hello world", "language": "en"}]

    def test_normal_mode_unaffected_by_default(self, monkeypatch, tmp_path):
        import backend.services.pipeline as pm
        p = self._make_pipeline(monkeypatch, tmp_path)
        assert p._test_mode is False
    def test_recommendations_have_required_fields(self):
        rec = recommend_local_models()
        assert rec["tier"] in ("low", "mid", "high")
        assert rec["recommended"]
        assert rec["whisper_recommendation"] in ("base", "small", "medium")
