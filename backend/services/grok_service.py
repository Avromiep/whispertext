"""Grok Voice Transcribe (xAI) — live streaming (WebSocket) with a batch fallback.

Mirrors deepgram_service: audio is streamed and transcribed *while the user is
still talking*, so on hotkey release the transcript is essentially ready. If the
stream fails, the pipeline falls back to Groq/local batch so a dictation is never
lost.

xAI's streaming API (wss://api.x.ai/v1/stt) is close to Deepgram's: raw PCM16
binary frames, `interim_results`, `endpointing`, `keyterm`, and the same
`{"type":"Finalize"}` push-to-talk control. Differences from Deepgram: Bearer auth,
`encoding=pcm`, transcript events are `transcript.partial`/`transcript.done` with
`is_final`/`speech_final`, and the stream is ended with `{"type":"audio.done"}`.

NOTE: this duplicates the transcript-assembly/clipboard-splice logic from
deepgram_service on purpose — keeping the two engines isolated so a change to one
can't break the other. Kept deliberately in sync with DeepgramLive.
"""
from __future__ import annotations

import asyncio
import json
import queue
import re
import time
from collections import Counter
from typing import Callable
from urllib.parse import urlencode

import httpx
import websockets

from backend.services.whisper_service import TranscriptionResult
from backend.utils.encryption import get_api_key
from backend.utils.logger import get_logger

log = get_logger(__name__)

PROVIDER_ID = "grok"
DEFAULT_MODEL = "grok-voice-transcribe-2.0"
LISTEN_WS = "wss://api.x.ai/v1/stt"
MODELS_URL = "https://api.x.ai/v1/models"

# Group a whole thought into one segment (see the Deepgram note); xAI's default is
# 400ms, which ends a segment at every micro-pause. 800ms reads more coherently.
_ENDPOINTING_MS = 800


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


async def validate(provider_id: str = PROVIDER_ID) -> dict:
    """Lightweight auth check via the models list — costs no transcription."""
    key = get_api_key(provider_id)
    if not key:
        return {"connected": False, "message": "No API key configured"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(MODELS_URL, headers=_auth(key))
        if r.status_code in (401, 403):
            return {"connected": False, "message": "Invalid API key"}
        r.raise_for_status()
        return {"connected": True, "message": "Connected",
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except httpx.HTTPError as exc:
        return {"connected": False, "message": str(exc)}


def _ws_url(model: str, sample_rate: int, language: str, keyterms: list[str],
            diarize: bool = False) -> str:
    params = [("model", model), ("encoding", "pcm"), ("sample_rate", str(sample_rate)),
              # Interim hypotheses stream in for the overlay's live preview; they're
              # display-only, so finals and release latency are unaffected.
              ("interim_results", "true"), ("endpointing", str(_ENDPOINTING_MS))]
    if diarize:
        params.append(("diarize", "true"))   # per-word speaker labels for main-speaker filtering
    if language and language != "auto":
        params.append(("language", language))
    for kt in keyterms or []:
        if kt.strip():
            params.append(("keyterm", kt.strip()[:50]))   # bias toward custom vocabulary
    return f"{LISTEN_WS}?{urlencode(params)}"


def _join_words(words: list[str]) -> str:
    """Rebuild text from individual words, tidying the spacing that word-level
    splitting leaves before punctuation ("hi , there" -> "hi, there")."""
    return re.sub(r"\s+([,.!?;:])", r"\1", " ".join(words)).strip()


class GrokLive:
    """A live streaming session. `feed()` is called from the audio thread with raw
    PCM16 at the capture sample rate; a background task ships it to xAI and finals
    are collected as they arrive. `finish()` flushes and returns the transcript."""

    def __init__(self, key: str, model: str, sample_rate: int,
                 language: str = "auto", keyterms: list[str] | None = None,
                 on_interim: Callable[[str], None] | None = None,
                 diarize: bool = False) -> None:
        self._key = key
        self._diarize = diarize
        self._url = _ws_url(model, sample_rate, language, keyterms or [], diarize)
        self._q: queue.Queue = queue.Queue()
        self._finals: list[str] = []
        self._inserts: list[tuple[int, str]] = []   # (finals-index, clipboard text)
        self._pending_clip: list[str] = []
        self._words: list[tuple[str, object]] = []   # (word, speaker) for main-speaker filtering
        self._last_tail = ""
        self._utt_had_chunk = False          # did a chunk-final arrive in the current utterance?
        self._final_event = asyncio.Event()  # set when any is_final lands (for the fast finish)
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
            log.warning("Grok connect failed: %s", exc)

    def feed(self, pcm_bytes: bytes) -> None:
        """Called from the audio callback thread — must be cheap (just enqueue)."""
        self._q.put_nowait(pcm_bytes)

    def insert_clipboard(self, text: str) -> None:
        """Queue `text` to splice in at the current point (the caller also calls
        finalize(), which flushes the words so far so the clip lands at the press
        point rather than at the start)."""
        if text:
            self._pending_clip.append(text)

    async def finalize(self) -> None:
        """Force xAI to finalize buffered audio now, so the words up to the key
        press become a segment and a queued clip lands after them."""
        self._emit_interim(self._last_tail)
        try:
            if self._ws is not None:
                await self._ws.send(json.dumps({"type": "Finalize"}))
        except Exception:
            pass

    def _render(self, tail: str = "") -> str:
        """Join finalized segments with clipboard inserts spliced in at the segment
        index they were captured at; `tail` (live, not-yet-final words) goes last."""
        by_idx: dict[int, list[str]] = {}
        for idx, txt in self._inserts:
            by_idx.setdefault(idx, []).append(txt)
        n = len(self._finals)
        parts: list[str] = []
        for i in range(n + 1):
            parts.extend(by_idx.get(i, []))
            if i == n:
                parts.extend(self._pending_clip)
            if i < n:
                parts.append(self._finals[i])
        if tail:
            parts.append(tail)
        return " ".join(p for p in parts if p).strip()

    def _accumulate_words(self, data: dict) -> None:
        """Collect per-word (word, speaker) from a final, for main-speaker
        filtering. No-op unless diarization is on."""
        if not self._diarize:
            return
        for w in data.get("words") or []:
            wt = (w.get("text") or w.get("word") or "").strip()
            if wt:
                self._words.append((wt, w.get("speaker")))

    def _main_speaker_text(self) -> str | None:
        """Keep only the dominant speaker's words (the user), dropping background
        voices. Returns None when there's nothing usable to filter (fall back to
        the plain transcript)."""
        labelled = [(wt, sp) for wt, sp in self._words if sp is not None]
        speakers = Counter(sp for _, sp in labelled)
        if len(speakers) < 2:
            return None   # zero or one speaker — nothing to isolate
        main = speakers.most_common(1)[0][0]
        # Keep the main speaker's words plus any unlabelled ones (safer than dropping).
        kept = [wt for wt, sp in self._words if sp == main or sp is None]
        return _join_words(kept) or None

    def _assemble(self) -> str:
        if self._pending_clip:
            idx = len(self._finals)
            self._inserts.extend((idx, clip) for clip in self._pending_clip)
            self._pending_clip = []
        if self._diarize:
            filtered = self._main_speaker_text()
            if filtered is not None:
                clips = " ".join(txt for _, txt in self._inserts)
                return (filtered + ((" " + clips) if clips else "")).strip()
        return self._render()

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

    def _commit_final(self, text: str) -> None:
        """A finalized segment: append it and place any queued clipboard inserts
        right after it (the press point), then refresh the preview."""
        if text:
            self._finals.append(text)
        if self._pending_clip:
            pending, self._pending_clip = self._pending_clip, []
            idx = len(self._finals)
            for clip in pending:
                self._inserts.append((idx, clip))
        self._emit_interim("")

    def _handle_message(self, data: dict) -> None:
        """Route one xAI event. transcript.partial (is_final) segments drive the
        live preview; transcript.done carries the authoritative full transcript
        used for the typed result."""
        etype = data.get("type")
        text = (data.get("text") or "").strip()
        if etype == "transcript.done" or (etype == "transcript.partial" and data.get("is_final")):
            # Privacy-safe structural trace (no dictated text — length only) for
            # diagnosing xAI event-flow changes; visible only in debug mode.
            log.debug("Grok event type=%s is_final=%s speech_final=%s len=%d",
                      etype, data.get("is_final"), data.get("speech_final"), len(text))
        if etype == "transcript.partial":
            if data.get("is_final"):
                if data.get("speech_final"):
                    # Utterance-final REPEATS the whole utterance (= all its
                    # chunk-finals concatenated). Only commit it if no chunk-final
                    # arrived for this utterance; otherwise it doubles the text.
                    if text and not self._utt_had_chunk:
                        self._commit_final(text)
                        self._accumulate_words(data)
                    self._utt_had_chunk = False    # next utterance starts fresh
                else:
                    self._commit_final(text)       # incremental chunk-final
                    self._accumulate_words(data)
                    self._utt_had_chunk = True
                self._final_event.set()            # a finalization landed — finish() can return
            elif text:
                self._emit_interim(text)           # live, not-yet-final tail
        # transcript.done is an empty end-of-stream marker (len 0) — nothing to do.

    def _emit_interim(self, tail: str) -> None:
        """Push the running transcript (finals + inserts + live tail) to the display
        callback. Display-only: never touches what finish() returns."""
        self._last_tail = tail
        if self._on_interim is None:
            return
        try:
            self._on_interim(self._render(tail))
        except Exception:
            pass

    async def finish(self, timeout: float = 8.0) -> str:
        """Return the transcript as fast as possible on hotkey release.

        Everything spoken up to the last pause is already in `_finals` (streamed
        live). Only the current tail needs finalizing, so send `Finalize` (xAI's
        push-to-talk fast-flush) and return the instant that final lands — instead
        of `audio.done`, whose end-of-stream wrap-up took ~2.2s. The socket is torn
        down in the background so it never blocks typing.
        """
        if self._failed or self._ws is None:
            return ""
        t0 = time.monotonic()
        self._q.put_nowait(None)
        try:
            if self._send_task:
                await asyncio.wait_for(self._send_task, timeout=4.0)
        except Exception:
            pass
        if self._last_tail:                        # words still pending — flush them
            self._final_event.clear()
            try:
                await self._ws.send(json.dumps({"type": "Finalize"}))
                await asyncio.wait_for(self._final_event.wait(), timeout=2.5)
            except Exception:
                pass
        text = self._assemble()
        try:
            asyncio.create_task(self._close_quietly())   # don't block on teardown
        except Exception:
            pass
        log.info("Grok finish: %.2fs (tail=%s)", time.monotonic() - t0, bool(self._last_tail))
        return text

    async def _close_quietly(self) -> None:
        """End the session server-side and close the socket, off the hot path."""
        try:
            await self._ws.send(json.dumps({"type": "audio.done"}))
        except Exception:
            pass
        try:
            await self._ws.close()
        except Exception:
            pass

    async def close(self) -> None:
        """Abandon the session without waiting for a transcript."""
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
              on_interim: Callable[[str], None] | None = None,
              diarize: bool = False) -> GrokLive | None:
    """A live session if a key is configured, else None (caller falls back)."""
    key = get_api_key(PROVIDER_ID)
    if not key:
        return None
    return GrokLive(key, model or DEFAULT_MODEL, sample_rate, language,
                    keyterms, on_interim, diarize=diarize)


def result(text: str, language: str) -> TranscriptionResult:
    return TranscriptionResult(text=text, language=language if language != "auto" else "en",
                               confidence=1.0, processing_s=0.0)
