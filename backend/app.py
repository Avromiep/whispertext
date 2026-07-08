"""WhisperText backend entry point.

Run with:  python -m backend.app
Starts the FastAPI service, installs the global hotkey hook, warms the
Whisper model, and purges expired history.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import APP_VERSION, BACKEND_HOST, BACKEND_PORT
from backend.models.settings import load_settings
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    setup_logging(debug=settings.general.debug_mode)
    log.info("WhisperText backend %s starting", APP_VERSION)
    migrate_legacy_keys()

    bus.attach_loop(asyncio.get_running_loop())

    # Wire global hotkeys to the dictation pipeline.
    hotkey_service.on_ptt_start = pipeline.ptt_start
    hotkey_service.on_ptt_stop = pipeline.ptt_stop
    hotkey_service.on_toggle = pipeline.toggle
    hotkey_service.start()

    # Background warm-up + history retention (non-blocking).
    threading.Thread(target=_warm_whisper, daemon=True).start()
    retention = settings.history.retention_days
    if settings.history.enabled and retention > 0:
        threading.Thread(target=pipeline.history.purge_older_than,
                         args=(retention,), daemon=True).start()

    yield

    hotkey_service.stop()
    log.info("WhisperText backend stopped")


app = FastAPI(title="WhisperText", version=APP_VERSION, lifespan=lifespan)
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
