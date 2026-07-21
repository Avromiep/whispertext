"""Dictation pipeline orchestrator.

Hotkey -> record (RAM) -> Faster-Whisper -> AI cleanup -> typing engine ->
history. Publishes overlay state at every stage:
idle -> listening -> transcribing -> cleaning -> typing -> done | error
"""
from __future__ import annotations

import asyncio
import threading
import time

from backend.models.settings import load_settings
from backend.services.audio_service import audio_service, speech_seconds
from backend.services.event_bus import bus
from backend.services.groq_whisper_service import (BACKUP_PROVIDER_ID, PROVIDER_ID,
                                                    groq_whisper_service)
from backend.services.llm_service import llm_service
from backend.services.typing_service import get_active_window_title, typing_service
from backend.services.whisper_service import whisper_service
from backend.storage.database import HistoryStore
from backend.utils import encryption
from backend.utils.logger import get_logger
from backend.utils.text import is_silence_hallucination

log = get_logger(__name__)

# A lone filler word is only discarded when less than this much speech was
# found — short enough that any deliberate one-word dictation clears it.
MIN_FILLER_SPEECH_S = 0.30


class DictationPipeline:
    def __init__(self) -> None:
        self.history = HistoryStore()
        self._busy = threading.Lock()          # one dictation at a time
        self._hands_free = False
        self._state_lock = threading.Lock()
        # Onboarding's mic test uses the real hotkey but must never type into
        # whatever window happens to have focus during setup — test mode
        # stops after transcription and reports the raw text over the
        # WebSocket instead of running cleanup/typing/history.
        self._test_mode = False
        # Persistent loop: keeps provider HTTP connection pools warm between
        # dictations (asyncio.run would tear them down every time).
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True,
                         name="pipeline-loop").start()

    def _run_async(self, coro, timeout_s: float = 90.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout_s)

    # ----------------------------------------------------------------- controls
    def ptt_start(self) -> None:
        """Hold-to-talk pressed."""
        with self._state_lock:
            if audio_service.is_recording:
                return
            self._hands_free = False
        self._start_recording()

    def ptt_stop(self) -> None:
        """Hold-to-talk released."""
        with self._state_lock:
            if not audio_service.is_recording or self._hands_free:
                return
        self._finish_recording()

    def set_test_mode(self, enabled: bool) -> None:
        self._test_mode = enabled

    def toggle(self) -> None:
        """Double-tap: start or stop hands-free recording."""
        with self._state_lock:
            recording = audio_service.is_recording
            if not recording:
                self._hands_free = True
        if recording:
            self._finish_recording()
        else:
            self._start_recording(hands_free=True)

    # ------------------------------------------------------------------- stages
    def _start_recording(self, hands_free: bool = False) -> None:
        try:
            audio_service.start()
            bus.status("listening", hands_free=hands_free)
        except RuntimeError as exc:
            bus.error(str(exc), code="no_microphone")

    def _finish_recording(self) -> None:
        audio = audio_service.stop()
        if audio.size == 0:  # nothing captured, or the buffer held only silence
            bus.status("idle")
            bus.notify("Didn't catch that — no speech detected.", "info")
            return
        # Process on a worker thread so the hook thread returns instantly.
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _process(self, audio) -> None:
        if not self._busy.acquire(blocking=False):
            bus.notify("Still processing the previous dictation…", "warning")
            return
        t0 = time.monotonic()
        target_app = get_active_window_title()
        try:
            bus.status("transcribing")
            result = self._transcribe(audio)
            t_whisper = time.monotonic() - t0
            if not result.text or self._is_hallucination(result.text, audio):
                bus.status("idle")
                bus.notify("Didn't catch that — no speech detected.", "info")
                return

            if self._test_mode:
                bus.publish("test_result", {"text": result.text, "language": result.language})
                bus.status("idle")
                return

            bus.status("cleaning")
            ai = self._run_async(llm_service.cleanup(result.text))
            t_ai = time.monotonic() - t0 - t_whisper
            final_text = self._apply_formatting(ai.text)
            if ai.error:
                bus.notify("AI cleanup unavailable — inserted raw transcription.",
                           "warning")

            bus.status("typing")
            typing_service.inject(final_text)

            elapsed = time.monotonic() - t0
            t_typing = elapsed - t_whisper - t_ai
            log.info("Stage timing: whisper=%.2fs ai=%.2fs (%s) typing=%.2fs total=%.2fs",
                     t_whisper, t_ai, ai.provider, t_typing, elapsed)
            bus.status("done", chars=len(final_text), seconds=round(elapsed, 2),
                       whisper_s=round(t_whisper, 2), ai_s=round(t_ai, 2))

            if load_settings().history.enabled:
                self.history.add(app=target_app, raw=result.text, final=final_text,
                                 duration_s=elapsed, provider=ai.provider,
                                 language=result.language)
            log.info("Dictation complete in %.2fs via %s (%d chars)",
                     elapsed, ai.provider, len(final_text))
        except Exception as exc:
            log.exception("Pipeline failed")
            bus.error(f"Dictation failed: {exc}")
        finally:
            self._busy.release()

    def _transcribe(self, audio):
        """Groq (fast cloud) when configured, trying a backup key (e.g. once
        the free tier on the primary account is exhausted) before finally
        falling back to local Whisper — a dictation is never lost just
        because a cloud call failed."""
        s = load_settings().whisper
        if s.engine == "groq":
            for provider_id in (PROVIDER_ID, BACKUP_PROVIDER_ID):
                key = encryption.get_api_key(provider_id)
                if not key:
                    continue
                try:
                    return self._run_async(groq_whisper_service.transcribe(
                        audio, language=s.language, model=s.groq_model, api_key=key),
                        timeout_s=20.0)
                except Exception as exc:
                    log.warning("Groq transcription failed via %s (%s); trying next",
                               provider_id, exc)
            bus.notify("Cloud transcription unavailable — used local instead.", "warning")
        return whisper_service.transcribe(audio)

    @staticmethod
    def _is_hallucination(text: str, audio) -> bool:
        """Reject a lone filler word produced from a blip that wasn't speech.

        A last resort behind the VAD gate, for audio that clears the detector
        on a cough or a door but contains no words. Gated on how much speech
        was actually found, not loudness — on a noisy microphone the noise
        floor and quiet speech sit at the same level. A spoken "Okay." runs
        well past this bound and survives.
        """
        if not is_silence_hallucination(text):
            return False
        detected = speech_seconds(audio, load_settings().audio.sample_rate)
        if detected >= MIN_FILLER_SPEECH_S:
            return False
        log.info("Discarding likely hallucination %r (%.2fs of speech detected)",
                 text, detected)
        return True

    @staticmethod
    def _apply_formatting(text: str) -> str:
        """Deterministic post-fixes independent of the LLM."""
        f = load_settings().formatting
        text = text.strip()
        if text and f.auto_capitalize:
            text = text[0].upper() + text[1:]
        return text


pipeline = DictationPipeline()
