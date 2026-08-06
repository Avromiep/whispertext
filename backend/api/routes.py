"""REST + WebSocket API consumed by the Electron frontend."""
from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.config import (APP_VERSION, LOG_DIR, SUPPORTED_LANGUAGES)
from backend.models.settings import load_settings, update_settings
from backend.services.audio_service import audio_service
from backend.services.event_bus import bus
from backend.services.groq_whisper_service import groq_whisper_service
from backend.services.hotkey_service import hotkey_service
from backend.services.llm_service import PROMPT_PRESETS, PROVIDER_CLASSES, llm_service
from backend.services.pipeline import pipeline
from backend.services.updater_service import check_for_updates
from backend.services.whisper_service import whisper_service
from backend.utils import encryption
from backend.utils.hardware import detect_hardware, recommend_local_models
from backend.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ health/meta
@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@router.get("/system/info")
async def system_info() -> dict:
    return {
        "version": APP_VERSION,
        "hardware": detect_hardware(),
        "recommendations": recommend_local_models(),
        "languages": SUPPORTED_LANGUAGES,
    }


@router.get("/system/stats")
async def system_stats() -> dict:
    import psutil
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_mb": round(psutil.Process().memory_info().rss / 2**20),
        "history": pipeline.history.stats(),
        "recording": audio_service.is_recording,
    }


# --------------------------------------------------------------------- settings
@router.get("/settings")
async def get_settings() -> dict:
    return load_settings().model_dump()


@router.patch("/settings")
async def patch_settings(patch: dict) -> dict:
    updated = update_settings(patch)
    bus.publish("settings_changed", {})
    return updated.model_dump()


class ApiKeyBody(BaseModel):
    provider: str
    key: str


@router.post("/settings/api-key")
async def set_api_key(body: ApiKeyBody) -> dict:
    ok = encryption.set_api_key(body.provider, body.key)
    return {"ok": ok}


@router.get("/settings/api-key/{provider}")
async def has_api_key(provider: str) -> dict:
    return {"provider": provider, "configured": encryption.has_api_key(provider)}


# -------------------------------------------------------------------- providers
@router.get("/providers")
async def list_providers() -> list[dict]:
    settings = load_settings()
    return [{
        "id": pid,
        "name": cls.display_name,
        "local": cls.is_local,
        "needs_api_key": cls.needs_api_key,
        "configured": (not cls.needs_api_key) or encryption.has_api_key(pid),
        "config": settings.ai.providers.get(pid, {}) and
                  settings.ai.providers[pid].model_dump(),
        "active": pid == settings.ai.provider,
    } for pid, cls in PROVIDER_CLASSES.items()]


@router.post("/providers/{provider_id}/validate")
async def validate_provider(provider_id: str) -> dict:
    try:
        status = await llm_service.validate_provider(provider_id)
        return status.__dict__
    except ValueError as exc:
        return JSONResponse({"connected": False, "message": str(exc)}, status_code=400)


@router.get("/providers/{provider_id}/models")
async def provider_models(provider_id: str) -> dict:
    try:
        p = llm_service.get_provider(provider_id)
        try:
            return {"models": await p.list_models()}
        finally:
            await p.shutdown()
    except Exception as exc:
        return JSONResponse({"models": [], "error": str(exc)}, status_code=502)


@router.get("/presets")
async def presets() -> dict:
    return PROMPT_PRESETS


# ------------------------------------------------------------------------ audio
@router.get("/audio/devices")
async def audio_devices() -> list[dict]:
    return audio_service.list_devices()


@router.post("/dictation/test")
async def dictation_test(seconds: float = 4.0) -> dict:
    """Onboarding mic test: record N seconds, transcribe, return text."""
    try:
        audio_service.start()
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    bus.status("listening", test=True)
    await asyncio.sleep(min(10.0, max(1.0, seconds)))
    audio = audio_service.stop()
    bus.status("transcribing")
    result = await asyncio.to_thread(whisper_service.transcribe, audio)
    bus.status("idle")
    return {"text": result.text, "language": result.language,
            "confidence": result.confidence, "processing_s": result.processing_s}


# -------------------------------------------------------------------- dictation
@router.post("/dictation/toggle")
async def dictation_toggle() -> dict:
    await asyncio.to_thread(pipeline.toggle)
    return {"recording": audio_service.is_recording}


@router.post("/dictation/pause")
async def dictation_pause(paused: bool = True) -> dict:
    hotkey_service.set_paused(paused)
    return {"paused": paused}


@router.post("/dictation/test-mode")
async def dictation_test_mode(enabled: bool = True) -> dict:
    """Onboarding's mic test: the real hotkey still triggers recording, but
    the pipeline stops after transcription (no cleanup/typing/history) and
    reports the raw text over the WebSocket as a "test_result" event."""
    pipeline.set_test_mode(enabled)
    return {"test_mode": enabled}


# ---------------------------------------------------------------------- hotkeys
@router.post("/hotkeys/record")
async def record_hotkey() -> dict:
    """Capture the next combo the user presses (for 'Record New Shortcut')."""
    hotkey_service.set_paused(True)
    try:
        combo = await asyncio.to_thread(hotkey_service.record_shortcut)
        return {"combo": combo}
    finally:
        hotkey_service.set_paused(False)


# ---------------------------------------------------------------------- history
@router.get("/history")
async def get_history(search: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
    return pipeline.history.list(search=search, limit=limit, offset=offset)


@router.post("/history/{entry_id}/favorite")
async def favorite(entry_id: int, value: bool = True) -> dict:
    pipeline.history.set_favorite(entry_id, value)
    return {"ok": True}


@router.delete("/history/{entry_id}")
async def delete_history_entry(entry_id: int) -> dict:
    pipeline.history.delete(entry_id)
    return {"ok": True}


@router.delete("/history")
async def clear_history() -> dict:
    pipeline.history.clear()
    return {"ok": True}


@router.get("/history/export")
async def export_history() -> StreamingResponse:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp", "app", "raw_transcript", "final_text",
                "duration_s", "provider", "language"])
    for e in pipeline.history.list(limit=100000):
        w.writerow([e["ts"], e["app"], e["raw_transcript"], e["final_text"],
                    e["duration_s"], e["provider"], e["language"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=whispertext-history.csv"})


@router.get("/vocabulary/export")
async def export_vocabulary() -> StreamingResponse:
    """The vocabulary as a plain-text file, one term per line — easy to back
    up, hand-edit, or move to another machine. Imported back on the client."""
    words = load_settings().vocabulary.words
    body = "".join(f"{w}\n" for w in words)
    return StreamingResponse(iter([body]), media_type="text/plain",
                             headers={"Content-Disposition":
                                      "attachment; filename=whispertext-vocabulary.txt"})


# ------------------------------------------------------------- groq transcribe
@router.post("/transcription/groq/validate")
async def validate_groq() -> dict:
    return await groq_whisper_service.validate()


@router.post("/transcription/groq/validate-backup")
async def validate_groq_backup() -> dict:
    from backend.services.groq_whisper_service import BACKUP_PROVIDER_ID
    return await groq_whisper_service.validate(BACKUP_PROVIDER_ID)


# ----------------------------------------------------------------- whisper mdls
@router.get("/models")
async def list_models() -> list[dict]:
    return whisper_service.installed_models()


@router.post("/models/{name}/download")
async def download_model(name: str) -> dict:
    # load_model downloads + caches; runs in a thread to keep the API responsive.
    await asyncio.to_thread(whisper_service.load_model, name)
    return {"ok": True}


@router.delete("/models/{name}")
async def delete_model(name: str) -> dict:
    return {"ok": whisper_service.delete_model(name)}


# ---------------------------------------------------------------------- updates
@router.post("/updates/check")
async def updates_check() -> dict:
    return await check_for_updates()


# ------------------------------------------------------------------------- logs
@router.get("/logs/export")
async def export_logs() -> StreamingResponse:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in Path(LOG_DIR).glob("*.log*"):
            z.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      "attachment; filename=whispertext-logs.zip"})


@router.get("/logs/tail")
async def tail_logs(lines: int = 400) -> dict:
    """The last `lines` lines of the current log, for viewing/copying in-app
    (so users can share logs without touching a terminal)."""
    lines = max(1, min(3000, lines))
    try:
        content = (Path(LOG_DIR) / "whispertext.log").read_text(
            encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        content = []
    tail = content[-lines:]
    return {"text": "\n".join(tail), "shown": len(tail), "total": len(content)}


# -------------------------------------------------------------------- websocket
HEARTBEAT_S = 5.0


@router.websocket("/ws")
async def websocket_events(ws: WebSocket) -> None:
    await ws.accept()
    q = bus.subscribe()
    try:
        while True:
            # A socket left half-open by sleep/resume stays readyState OPEN on
            # the client without ever firing onclose, which silently strands the
            # overlay. The steady heartbeat gives it something to watchdog.
            try:
                payload = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                payload = json.dumps({"type": "heartbeat", "ts": time.time()})
            await ws.send_text(payload)
    except (WebSocketDisconnect, RuntimeError, ConnectionError):
        pass
    finally:
        bus.unsubscribe(q)
