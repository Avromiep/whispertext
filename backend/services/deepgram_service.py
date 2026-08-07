"""Deepgram transcription — live streaming (WebSocket) with a batch fallback.

Streaming is the whole point of Deepgram here: audio is sent and transcribed
*while the user is still talking*, so on hotkey release the transcript is
essentially ready — unlike Groq/Whisper, which can only process the whole clip
after release. If streaming fails for any reason, the pipeline falls back to
Groq/local batch, so a dictation is never lost.
"""
from __future__ import annotations

import asyncio
import json
import queue
import time
from urllib.parse import urlencode

import httpx
import websockets

from backend.services.whisper_service import TranscriptionResult
from backend.utils.encryption import get_api_key
from backend.utils.logger import get_logger

log = get_logger(__name__)

PROVIDER_ID = "deepgram"
DEFAULT_MODEL = "nova-3"
LISTEN_WS = "wss://api.deepgram.com/v1/listen"
PROJECTS_URL = "https://api.deepgram.com/v1/projects"


def _auth(key: str) -> dict:
    return {"Authorization": f"Token {key}"}


async def validate(provider_id: str = PROVIDER_ID) -> dict:
    """Lightweight auth check via the projects list — costs no transcription."""
    key = get_api_key(provider_id)
    if not key:
        return {"connected": False, "message": "No API key configured"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(PROJECTS_URL, headers=_auth(key))
        if r.status_code in (401, 403):
            return {"connected": False, "message": "Invalid API key"}
        r.raise_for_status()
        return {"connected": True, "message": "Connected",
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except httpx.HTTPError as exc:
        return {"connected": False, "message": str(exc)}


def _ws_url(model: str, sample_rate: int, language: str, keyterms: list[str]) -> str:
    params = [("model", model), ("encoding", "linear16"), ("sample_rate", str(sample_rate)),
              ("channels", "1"), ("punctuate", "true"), ("smart_format", "true"),
              ("interim_results", "false")]
    if language and language != "auto":
        params.append(("language", language))
    for kt in keyterms or []:
        if kt.strip():
            params.append(("keyterm", kt.strip()))   # bias toward custom vocabulary
    return f"{LISTEN_WS}?{urlencode(params)}"


class DeepgramLive:
    """A live streaming session. `feed()` is called from the audio thread with
    raw linear16 PCM at the capture sample rate; a background task ships it to
    Deepgram, and finals are collected as they arrive. `finish()` flushes and
    returns the full transcript."""

    def __init__(self, key: str, model: str, sample_rate: int,
                 language: str = "auto", keyterms: list[str] | None = None) -> None:
        self._key = key
        self._url = _ws_url(model, sample_rate, language, keyterms or [])
        self._q: queue.Queue = queue.Queue()   # thread-safe: audio thread -> loop
        self._finals: list[str] = []
        self._ws = None
        self._send_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._failed = False

    async def start(self) -> None:
        try:
            self._ws = await websockets.connect(
                self._url, additional_headers=_auth(self._key), open_timeout=6)
            self._recv_task = asyncio.create_task(self._recv())
            self._send_task = asyncio.create_task(self._send())
        except Exception as exc:
            self._failed = True
            log.warning("Deepgram connect failed: %s", exc)

    def feed(self, pcm_bytes: bytes) -> None:
        """Called from the audio callback thread — must be cheap (just enqueue)."""
        self._q.put_nowait(pcm_bytes)

    async def _send(self) -> None:
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            if item is None:            # sentinel from finish()
                break
            try:
                await self._ws.send(item)
            except Exception:
                break

    async def _recv(self) -> None:
        try:
            async for msg in self._ws:
                data = json.loads(msg)
                if data.get("type") == "Results" and data.get("is_final"):
                    alts = data.get("channel", {}).get("alternatives", [])
                    if alts and alts[0].get("transcript"):
                        self._finals.append(alts[0]["transcript"])
        except Exception:
            pass

    async def finish(self, timeout: float = 8.0) -> str:
        """Flush queued audio, ask Deepgram to finalize, return the transcript.
        Fast on release because most audio was already sent during the hold."""
        if self._failed or self._ws is None:
            return ""
        self._q.put_nowait(None)                       # stop the send loop after draining
        try:
            if self._send_task:
                await asyncio.wait_for(self._send_task, timeout=timeout)
        except Exception:
            pass
        try:
            await self._ws.send(json.dumps({"type": "CloseStream"}))  # flush + close server-side
            if self._recv_task:
                await asyncio.wait_for(self._recv_task, timeout=timeout)
        except Exception:
            pass
        try:
            await self._ws.close()
        except Exception:
            pass
        return " ".join(self._finals).strip()

    async def close(self) -> None:
        """Abandon the session (e.g. no speech) without waiting for a transcript."""
        self._q.put_nowait(None)
        for task in (self._send_task, self._recv_task):
            if task:
                task.cancel()
        try:
            if self._ws:
                await self._ws.close()
        except Exception:
            pass


def make_live(model: str, sample_rate: int, language: str,
              keyterms: list[str] | None = None) -> DeepgramLive | None:
    """A live session if a key is configured, else None (caller falls back)."""
    key = get_api_key(PROVIDER_ID)
    if not key:
        return None
    return DeepgramLive(key, model or DEFAULT_MODEL, sample_rate, language, keyterms)


def result(text: str, language: str) -> TranscriptionResult:
    return TranscriptionResult(text=text, language=language if language != "auto" else "en",
                               confidence=1.0, processing_s=0.0)
