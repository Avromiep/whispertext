"""WhisperText backend entry point.

Run with:  python -m backend.app
Starts the FastAPI service, installs the global hotkey hook, warms the
Whisper model, and purges expired history.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import router
from backend.config import APP_VERSION, BACKEND_HOST, BACKEND_PORT
from backend.utils.api_token import ensure_token, token_ok
from backend.models.settings import load_settings
from backend.services.audio_service import speech_seconds
from backend.services.event_bus import bus
from backend.services.hotkey_service import hotkey_service
from backend.services.pipeline import pipeline
from backend.services.whisper_service import whisper_service
from backend.utils.encryption import migrate_legacy_keys
from backend.utils.logger import get_logger, setup_logging

log = get_logger(__name__)


def _warm_whisper() -> None:
    """Preload the configured Whisper model so the first dictation is fast."""
    try:
        whisper_service.load_model()
    except Exception as exc:
        log.warning("Whisper preload deferred: %s", exc)
        bus.notify(f"Speech model not ready yet: {exc}", "warning")


def _warm_vad() -> None:
    """Preload Silero, which gates every recording — including on the Groq
    path, where it is the only thing standing between an empty room and a
    hallucinated word."""
    try:
        speech_seconds(np.zeros(16000, dtype=np.float32), 16000)
    except Exception as exc:
        log.warning("VAD preload deferred: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    setup_logging(debug=settings.general.debug_mode)
    log.info("WhisperText backend %s starting", APP_VERSION)
    ensure_token()          # fresh local-API token before the server serves anything
    migrate_legacy_keys()

    bus.attach_loop(asyncio.get_running_loop())

    # Wire global hotkeys to the dictation pipeline.
    hotkey_service.on_ptt_start = pipeline.ptt_start
    hotkey_service.on_ptt_stop = pipeline.ptt_stop
    hotkey_service.on_toggle = pipeline.toggle
    hotkey_service.on_clipboard_insert = pipeline.clipboard_insert
    hotkey_service.start()

    # Background warm-up + history retention (non-blocking).
    threading.Thread(target=_warm_whisper, daemon=True).start()
    threading.Thread(target=_warm_vad, daemon=True).start()
    retention = settings.history.retention_days
    if settings.history.enabled and retention > 0:
        threading.Thread(target=pipeline.history.purge_older_than,
                         args=(retention,), daemon=True).start()

    yield

    hotkey_service.stop()
    log.info("WhisperText backend stopped")


app = FastAPI(title="WhisperText", version=APP_VERSION, lifespan=lifespan)

# Endpoints reachable without the token: only the liveness check, so the app can
# always tell the backend is up before it has read the token.
_OPEN_PATHS = {"/health"}


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    """Reject any request that doesn't carry the shared local-API token. Blocks
    a web page or other process that merely knows the port. OPTIONS (CORS
    preflight) and the health check pass through."""
    if request.method == "OPTIONS" or request.url.path in _OPEN_PATHS:
        return await call_next(request)
    if not token_ok(request.headers.get("x-wt-token")):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "app://."],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


def main() -> None:
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT, log_level="warning")


if __name__ == "__main__":
    main()
