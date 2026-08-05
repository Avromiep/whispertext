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
from backend.utils.text import (apply_vocabulary_casing, build_vocabulary_prompt,
                                 is_silence_hallucination)

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
        """Double-tap: start hands-free recording, or stop it if already going.

        Stopping is also automatic once you go quiet (see the endpoint
        monitor); the second double-tap is a manual override for either
        ending early or when auto-stop is turned off."""
        with self._state_lock:
            if audio_service.is_recording:
                if not self._hands_free:
                    return  # a push-to-talk hold is in progress; leave it alone
                self._hands_free = False  # claim the stop so the monitor bows out
                stop = True
            else:
                self._hands_free = True
                stop = False
        if stop:
            self._finish_recording()
        else:
            self._start_recording(hands_free=True)

    # ------------------------------------------------------------------- stages
    def _start_recording(self, hands_free: bool = False) -> None:
        try:
            audio_service.start()
        except RuntimeError as exc:
            bus.error(str(exc), code="no_microphone")
            return
        bus.status("listening", hands_free=hands_free)
        if hands_free and load_settings().hotkeys.hands_free_auto_stop:
            threading.Thread(target=self._hands_free_endpoint, daemon=True,
                             name="hands-free-endpoint").start()

    def _hands_free_endpoint(self) -> None:
        """End a hands-free dictation when the speaker stops talking.

        Uses the same Silero VAD as the silence gate, run on a rolling
        window, so it works even on a noisy microphone where a loudness
        threshold could not tell speech from room tone. Also stops if the
        user double-taps to launch but never speaks, instead of recording
        forever."""
        hk = load_settings().hotkeys
        rate = load_settings().audio.sample_rate
        silence_timeout = max(0.5, hk.hands_free_silence_ms / 1000)
        # If they never speak, give up a bit after the trailing-silence bound.
        no_speech_timeout = max(4.0, silence_timeout + 2.0)
        window_s, poll_s = 1.2, 0.25

        started = time.monotonic()
        last_voice: float | None = None
        while audio_service.is_recording and self._hands_free:
            tail = audio_service.tail_audio(window_s)
            voiced = tail.size > 0 and speech_seconds(tail, rate) >= 0.15
            now = time.monotonic()
            if voiced:
                last_voice = now
            elif last_voice is not None:
                if now - last_voice >= silence_timeout:
                    self._auto_finish("trailing silence")
                    return
            elif now - started >= no_speech_timeout:
                self._auto_finish("no speech")
                return
            time.sleep(poll_s)

    def _auto_finish(self, reason: str) -> None:
        """Finish a hands-free recording from the endpoint monitor, unless a
        manual double-tap already claimed the stop."""
        with self._state_lock:
            if not audio_service.is_recording or not self._hands_free:
                return
            self._hands_free = False
        log.info("Hands-free auto-stop: %s", reason)
        self._finish_recording()

    def _finish_recording(self) -> None:
        audio = audio_service.stop()
        cap = getattr(audio_service, "last_capture", None)
        if cap and cap.get("dropped"):
            # The mic didn't deliver the whole recording — warn so a cut-off
            # dictation isn't silent. The (partial) audio is still processed.
            bus.notify(
                f"Your mic dropped about {cap['dropped_s']:.0f}s of audio — the text may be "
                "cut off. Try again, and check no other app (e.g. VoiceAttack) is using the mic.",
                "warning")
        if audio.size == 0:  # nothing captured, or the buffer held only silence
            self._report_no_speech()
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
                self._report_no_speech()
                return

            if self._test_mode:
                bus.publish("test_result", {"text": result.text, "language": result.language})
                bus.status("idle")
                return

            bus.status("cleaning")
            ai = self._run_async(llm_service.cleanup(result.text))
            t_ai = time.monotonic() - t0 - t_whisper
            final_text = self._apply_formatting(ai.text)
            # Enforce the exact spelling/casing of vocabulary terms last, so
            # neither AI cleanup nor auto-capitalize can re-case them.
            final_text = apply_vocabulary_casing(
                final_text, load_settings().vocabulary.words)
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
        cfg = load_settings()
        s = cfg.whisper
        if s.engine == "groq":
            prompt = build_vocabulary_prompt(cfg.vocabulary.words)
            for provider_id in (PROVIDER_ID, BACKUP_PROVIDER_ID):
                key = encryption.get_api_key(provider_id)
                if not key:
                    continue
                try:
                    return self._run_async(groq_whisper_service.transcribe(
                        audio, language=s.language, model=s.groq_model, api_key=key,
                        prompt=prompt),
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
    def _report_no_speech() -> None:
        """Tell the overlay to flash a brief 'no speech' pill, rather than
        firing a desktop notification that slides in from the screen corner.
        The overlay shows it in place of the recording pill, then hides."""
        bus.status("empty")

    @staticmethod
    def _apply_formatting(text: str) -> str:
        """Deterministic post-fixes independent of the LLM."""
        f = load_settings().formatting
        text = text.strip()
        if text and f.auto_capitalize:
            text = text[0].upper() + text[1:]
        return text


pipeline = DictationPipeline()
