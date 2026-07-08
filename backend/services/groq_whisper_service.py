"""Groq-hosted Whisper transcription — a fast, purpose-built cloud ASR path.

Groq runs Whisper on inference hardware built specifically for speed
(independently benchmarked at 200-300x real-time), the same class of
infrastructure commercial dictation apps rely on for their "instant" feel.
Local CPU transcription (whisper_service.py) can't match this without a
CUDA GPU, so this is offered as an optional, much faster alternative, with
automatic fallback to local Whisper if the cloud call fails for any reason
(no internet, bad key, rate limit) — the pipeline never loses a dictation.
"""
from __future__ import annotations

import io
import time
import wave

import httpx
import numpy as np

from backend.services.whisper_service import TranscriptionResult
from backend.utils.encryption import get_api_key
from backend.utils.logger import get_logger

log = get_logger(__name__)

API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODELS_URL = "https://api.groq.com/openai/v1/models"
DEFAULT_MODEL = "whisper-large-v3-turbo"
PROVIDER_ID = "groq"
BACKUP_PROVIDER_ID = "groq_backup"  # a second key/account, e.g. once the free tier is exhausted


def encode_wav(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Float32 mono [-1, 1] -> 16-bit PCM WAV bytes, for upload as a file."""
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class GroqWhisperService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def transcribe(self, audio: np.ndarray, *, language: str = "auto",
                         model: str = DEFAULT_MODEL,
                         api_key: str | None = None) -> TranscriptionResult:
        api_key = api_key or get_api_key(PROVIDER_ID)
        if not api_key:
            raise RuntimeError("No Groq API key configured")
        if audio.size < 1600:  # < 0.1s — nothing meaningful was said
            return TranscriptionResult("", "en", 0.0, 0.0)

        t0 = time.monotonic()
        wav_bytes = encode_wav(audio)
        data = {"model": model, "response_format": "json"}
        if language != "auto":
            data["language"] = language
        r = await self.client.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data=data,
        )
        r.raise_for_status()
        text = r.json().get("text", "").strip()
        elapsed = time.monotonic() - t0
        log.info("Groq transcribed %.1fs audio in %.2fs: %r",
                 audio.size / 16000, elapsed, text[:80])
        return TranscriptionResult(
            text=text, language=language if language != "auto" else "en",
            confidence=1.0, processing_s=round(elapsed, 3))

    async def validate(self, provider_id: str = PROVIDER_ID) -> dict:
        """Lightweight auth check via the models list — costs no transcription quota."""
        api_key = get_api_key(provider_id)
        if not api_key:
            return {"connected": False, "message": "No API key configured"}
        t0 = time.monotonic()
        try:
            r = await self.client.get(MODELS_URL, headers={"Authorization": f"Bearer {api_key}"})
            r.raise_for_status()
            return {"connected": True, "message": "Connected",
                    "latency_ms": int((time.monotonic() - t0) * 1000)}
        except httpx.HTTPStatusError as exc:
            msg = ("Invalid API key" if exc.response.status_code in (401, 403)
                   else f"HTTP {exc.response.status_code}")
            return {"connected": False, "message": msg}
        except httpx.HTTPError as exc:
            return {"connected": False, "message": str(exc)}

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


groq_whisper_service = GroqWhisperService()
