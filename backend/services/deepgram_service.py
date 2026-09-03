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
from typing import Callable
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


async def balance(provider_id: str = PROVIDER_ID) -> dict:
    """Remaining credit on the Deepgram account: {ok, amount, units} or
    {ok: False, message}. Sums the balances of the first project."""
    key = get_api_key(provider_id)
    if not key:
        return {"ok": False, "message": "No API key configured"}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            pr = await c.get(PROJECTS_URL, headers=_auth(key))
            if pr.status_code in (401, 403):
                return {"ok": False, "message": "Invalid API key"}
            pr.raise_for_status()
            projects = pr.json().get("projects", [])
            if not projects:
                return {"ok": False, "message": "No Deepgram project found"}
            pid = projects[0]["project_id"]
            br = await c.get(f"{PROJECTS_URL}/{pid}/balances", headers=_auth(key))
            if br.status_code == 403:
                # Reading billing needs an Admin/Owner-scoped key; a Member key
                # (fine for transcription) can't. Tell the user how to fix it.
                return {"ok": False, "needs_admin": True,
                        "message": "This key can't read your balance — it needs Admin permission. "
                                   "Create an Admin key at console.deepgram.com (or check the balance there)."}
            br.raise_for_status()
            balances = br.json().get("balances", [])
            if not balances:
                return {"ok": False, "message": "No balance on this account"}
            total = sum(float(b.get("amount", 0)) for b in balances)
            units = balances[0].get("units", "usd")
            return {"ok": True, "amount": round(total, 2), "units": units}
    except httpx.HTTPError as exc:
        return {"ok": False, "message": str(exc)}


# Deepgram ends a segment (and drops a terminal period) after this much silence.
# Its ~10ms default treats every little dictation pause as a sentence end, which
# is why natural speech came out as many one-clause "sentences" (and lone words
# like "Sometimes."). Waiting for a real ~0.8s pause groups a whole thought into
# one segment it can punctuate coherently. Segments still finalize DURING the
# hold (real-time), so releasing the key stays instant — only the last short
# segment is flushed on release.
_ENDPOINTING_MS = 800


def _ws_url(model: str, sample_rate: int, language: str, keyterms: list[str],
            numerals: bool = True) -> str:
    params = [("model", model), ("encoding", "linear16"), ("sample_rate", str(sample_rate)),
              ("channels", "1"), ("punctuate", "true"), ("smart_format", "true"),
              # Interim hypotheses stream in as the user speaks so the overlay can
              # show a live preview. They're display-only and free (billing is by
              # audio duration): finals are unchanged, so the TYPED text and the
              # release latency are identical to interim_results=false.
              ("interim_results", "true"), ("endpointing", str(_ENDPOINTING_MS))]
    if numerals:
        # Force spoken numbers to digits (three -> 3); smart_format alone spells
        # small numbers out per writing style.
        params.append(("numerals", "true"))
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
                 language: str = "auto", keyterms: list[str] | None = None,
                 numerals: bool = True,
                 on_interim: Callable[[str], None] | None = None) -> None:
        self._key = key
        self._url = _ws_url(model, sample_rate, language, keyterms or [], numerals)
        self._q: queue.Queue = queue.Queue()   # thread-safe: audio thread -> loop
        self._finals: list[str] = []
        self._inserts: list[tuple[int, str]] = []   # (finals-index, clipboard text) to splice
        self._pending_clip: list[str] = []          # clips awaiting the next finalized segment
        # Display-only callback fed the running transcript (committed finals plus
        # the current interim tail) so the overlay can show a live preview. Never
        # affects the returned transcript; guarded so a UI error can't break recv.
        self._on_interim = on_interim
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

    def insert_clipboard(self, text: str) -> None:
        """Queue `text` to splice in at the current point. The caller also calls
        finalize(), which forces Deepgram to flush the words spoken so far into a
        final segment; the clip is then placed right after that segment (see
        _handle_message), so it lands where the key was pressed — not at the
        start, which is where a naive finals-count would put it (finals lag)."""
        if text:
            self._pending_clip.append(text)

    async def finalize(self) -> None:
        """Ask Deepgram to finalize buffered audio now, so the words spoken up to
        the key press become a segment and the queued clip lands after them."""
        try:
            if self._ws is not None:
                await self._ws.send(json.dumps({"type": "Finalize"}))
        except Exception:
            pass

    def _assemble(self) -> str:
        """Join finalized segments with any clipboard inserts spliced in at the
        segment index they were captured at."""
        # Any clip still pending (its finalize produced no further final) goes at
        # the current end so it's never dropped.
        if self._pending_clip:
            idx = len(self._finals)
            self._inserts.extend((idx, clip) for clip in self._pending_clip)
            self._pending_clip = []
        by_idx: dict[int, list[str]] = {}
        for idx, txt in self._inserts:
            by_idx.setdefault(idx, []).append(txt)
        parts: list[str] = []
        for i in range(len(self._finals) + 1):
            parts.extend(by_idx.get(i, []))
            if i < len(self._finals):
                parts.append(self._finals[i])
        return " ".join(p for p in parts if p).strip()

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
                self._handle_message(json.loads(msg))
        except Exception:
            pass

    def _handle_message(self, data: dict) -> None:
        """Route one Deepgram message: finals build the returned transcript;
        interim + final both refresh the live overlay preview."""
        if data.get("type") != "Results":
            return
        alts = data.get("channel", {}).get("alternatives", [])
        transcript = alts[0].get("transcript") if alts else ""
        if data.get("is_final"):
            if transcript:
                self._finals.append(transcript)
            # Place any clipboard inserts the user requested since the last
            # finalize: they go right after the words just finalized (which the
            # user's key press flushed via finalize()), i.e. at the press point.
            if self._pending_clip:
                pending, self._pending_clip = self._pending_clip, []
                idx = len(self._finals)
                for clip in pending:
                    self._inserts.append((idx, clip))
            self._emit_interim("")                # tail consumed into finals
        elif transcript:
            self._emit_interim(transcript)        # live, not-yet-final tail

    def _emit_interim(self, tail: str) -> None:
        """Push the running transcript (committed finals + live tail) to the
        display callback. Display-only: never touches what finish() returns."""
        if self._on_interim is None:
            return
        parts = self._finals + ([tail] if tail else [])
        try:
            self._on_interim(" ".join(parts).strip())
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
        return self._assemble()

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
              keyterms: list[str] | None = None,
              numerals: bool = True,
              on_interim: Callable[[str], None] | None = None) -> DeepgramLive | None:
    """A live session if a key is configured, else None (caller falls back)."""
    key = get_api_key(PROVIDER_ID)
    if not key:
        return None
    return DeepgramLive(key, model or DEFAULT_MODEL, sample_rate, language,
                        keyterms, numerals, on_interim)


def result(text: str, language: str) -> TranscriptionResult:
    return TranscriptionResult(text=text, language=language if language != "auto" else "en",
                               confidence=1.0, processing_s=0.0)
