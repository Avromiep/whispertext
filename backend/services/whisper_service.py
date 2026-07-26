"""Faster-Whisper (CTranslate2) transcription with GPU auto-detect and CPU fallback.

Models are lazily loaded, cached in memory, and downloaded automatically to the
app's model cache directory with progress events for the Models page.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import numpy as np

from backend.config import MODEL_CACHE_DIR, WHISPER_MODELS
from backend.models.settings import load_settings
from backend.services.event_bus import bus
from backend.utils.hardware import detect_hardware
from backend.utils.logger import get_logger
from backend.utils.text import build_vocabulary_prompt, strip_trailing_ellipsis

log = get_logger(__name__)

# Segments Whisper is more than this confident are silence are discarded.
NO_SPEECH_MAX = 0.6


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    processing_s: float


class WhisperService:
    def __init__(self) -> None:
        self._model = None
        self._model_name: str | None = None
        self._device: str | None = None
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- loading
    def _resolve_device(self) -> tuple[str, str]:
        pref = load_settings().whisper.compute_device
        if pref == "cpu":
            return "cpu", "int8"
        if pref == "cuda" or (pref == "auto" and detect_hardware()["cuda"]):
            return "cuda", "float16"
        return "cpu", "int8"

    def load_model(self, name: str | None = None) -> None:
        """Load (and download if needed) the configured model. Thread-safe."""
        from faster_whisper import WhisperModel  # deferred: heavy import

        name = name or load_settings().whisper.model
        device, compute = self._resolve_device()
        with self._lock:
            if self._model is not None and self._model_name == name and self._device == device:
                return
            bus.publish("model_download", {"model": name, "state": "loading"})
            t0 = time.monotonic()
            # CTranslate2 defaults to 4 CPU threads regardless of core count.
            # Use all physical cores on CPU; irrelevant (and harmless) on CUDA.
            cpu_threads = os.cpu_count() or 4
            try:
                self._model = WhisperModel(
                    name, device=device, compute_type=compute,
                    cpu_threads=cpu_threads, download_root=str(MODEL_CACHE_DIR))
            except (RuntimeError, OSError, ValueError) as exc:
                if device == "cuda":
                    # Graceful CPU fallback per spec — never crash on CUDA issues.
                    log.warning("CUDA load failed (%s); falling back to CPU int8", exc)
                    self._model = WhisperModel(
                        name, device="cpu", compute_type="int8", cpu_threads=cpu_threads,
                        download_root=str(MODEL_CACHE_DIR))
                    device = "cpu"
                else:
                    bus.publish("model_download", {"model": name, "state": "error",
                                                   "message": str(exc)})
                    raise
            self._model_name, self._device = name, device
            log.info("Whisper '%s' ready on %s in %.1fs", name, device,
                     time.monotonic() - t0)
            bus.publish("model_download", {"model": name, "state": "ready",
                                           "device": device})

    # ------------------------------------------------------------ transcription
    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        """Transcribe a float32 mono 16 kHz buffer from RAM."""
        if audio.size < 1600:  # < 0.1 s — nothing meaningful was said
            return TranscriptionResult("", "en", 0.0, 0.0)
        self.load_model()
        assert self._model is not None

        cfg = load_settings()
        s = cfg.whisper
        lang = None if s.language == "auto" else s.language
        t0 = time.monotonic()
        segments, info = self._model.transcribe(
            audio, language=lang, beam_size=s.beam_size, vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                # Drop sub-200 ms blips — a keyboard click or breath that trips
                # the VAD is otherwise passed to Whisper, which answers with a
                # filler word rather than nothing.
                "min_speech_duration_ms": 200,
            },
            # Bias decoding toward the user's custom vocabulary (proper nouns,
            # jargon) so those terms are transcribed rather than guessed at.
            initial_prompt=build_vocabulary_prompt(cfg.vocabulary.words),
            # Independent utterances: skipping cross-segment conditioning is
            # faster and avoids repetition loops in noisy audio.
            condition_on_previous_text=False,
            no_speech_threshold=NO_SPEECH_MAX)
        # Whisper reports its own confidence that a segment is silence; honour
        # it explicitly rather than relying on the internal fallback heuristics.
        kept = [seg for seg in segments if seg.no_speech_prob < NO_SPEECH_MAX]
        text = strip_trailing_ellipsis(" ".join(seg.text.strip() for seg in kept).strip())
        elapsed = time.monotonic() - t0

        log.info("Transcribed %.1fs audio in %.2fs (%s): %r",
                 audio.size / 16000, elapsed, info.language, text[:80])
        return TranscriptionResult(
            text=text,
            language=info.language,
            confidence=round(float(info.language_probability), 3),
            processing_s=round(elapsed, 3),
        )

    # ---------------------------------------------------------------- models UI
    def installed_models(self) -> list[dict]:
        """Status of every catalog model for the Models page."""
        out = []
        for name, meta in WHISPER_MODELS.items():
            # faster-whisper caches HF snapshots as models--Systran--faster-whisper-<name>
            marker = MODEL_CACHE_DIR / f"models--Systran--faster-whisper-{name}"
            out.append({
                "name": name,
                **meta,
                "installed": marker.exists(),
                "active": name == load_settings().whisper.model,
                "loaded": name == self._model_name,
                "device": self._device if name == self._model_name else None,
            })
        return out

    def delete_model(self, name: str) -> bool:
        import shutil
        marker = MODEL_CACHE_DIR / f"models--Systran--faster-whisper-{name}"
        if marker.exists():
            with self._lock:
                if self._model_name == name:
                    self._model = None
                    self._model_name = None
            shutil.rmtree(marker, ignore_errors=True)
            return True
        return False


whisper_service = WhisperService()
