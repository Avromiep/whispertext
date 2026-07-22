"""Application-wide paths and constants for the WhisperText backend."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_NAME = "WhisperText"
_LEGACY_APP_NAME = "WhisperType"  # pre-rename name; migrated from once, below
APP_VERSION = "1.0.19"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 43117  # fixed local port; frontend discovers it via this constant

# ---------------------------------------------------------------------------
# Filesystem layout — everything lives under %APPDATA%/WhisperText
# ---------------------------------------------------------------------------
_APPDATA_ROOT = Path(os.environ.get("APPDATA", str(Path.home())))
APP_DIR = _APPDATA_ROOT / APP_NAME
SETTINGS_FILE = APP_DIR / "settings.json"
DB_FILE = APP_DIR / "whispertext.db"
LOG_DIR = APP_DIR / "logs"
MODEL_CACHE_DIR = APP_DIR / "models"


def _migrate_legacy_app_dir() -> None:
    """One-time copy of settings/history/logs/models from the pre-rename
    (WhisperType) data folder, so renaming the app doesn't lose user data."""
    legacy_dir = _APPDATA_ROOT / _LEGACY_APP_NAME
    if APP_DIR.exists() or not legacy_dir.exists():
        return
    shutil.copytree(legacy_dir, APP_DIR)
    legacy_db = APP_DIR / "whispertype.db"
    if legacy_db.exists() and not DB_FILE.exists():
        legacy_db.rename(DB_FILE)
    legacy_db_wal = APP_DIR / "whispertype.db-wal"
    if legacy_db_wal.exists():
        legacy_db_wal.rename(APP_DIR / "whispertext.db-wal")
    legacy_db_shm = APP_DIR / "whispertype.db-shm"
    if legacy_db_shm.exists():
        legacy_db_shm.rename(APP_DIR / "whispertext.db-shm")


_migrate_legacy_app_dir()
for _d in (APP_DIR, LOG_DIR, MODEL_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Keyring namespace for secure API-key storage (Windows Credential Manager).
KEYRING_SERVICE = "WhisperText"
LEGACY_KEYRING_SERVICE = "WhisperType"

# Whisper model catalog shown on the Models page. Sizes are approximate
# download sizes for the CTranslate2 conversions used by faster-whisper.
# The ".en" variants are English-only: slightly faster (no multilingual
# token overhead) and marginally more accurate for English speech, but only
# usable when Dictation > Language is pinned to English rather than "auto".
WHISPER_MODELS = {
    "tiny":    {"size_mb": 75,   "ram_gb": 1.0, "accuracy": 2, "speed": 5},
    "tiny.en": {"size_mb": 75,   "ram_gb": 1.0, "accuracy": 2, "speed": 5},
    "base":    {"size_mb": 145,  "ram_gb": 1.0, "accuracy": 3, "speed": 5},
    "base.en": {"size_mb": 145,  "ram_gb": 1.0, "accuracy": 3, "speed": 5},
    "small":  {"size_mb": 484,  "ram_gb": 2.0, "accuracy": 4, "speed": 4},
    "medium": {"size_mb": 1530, "ram_gb": 5.0, "accuracy": 4, "speed": 3},
    "large-v3": {"size_mb": 3100, "ram_gb": 10.0, "accuracy": 5, "speed": 2},
}

SUPPORTED_LANGUAGES = {
    "auto": "Auto-detect", "en": "English", "es": "Spanish", "fr": "French",
    "de": "German", "he": "Hebrew", "ja": "Japanese", "zh": "Chinese",
    "it": "Italian", "pt": "Portuguese", "ar": "Arabic", "ru": "Russian",
    "ko": "Korean", "nl": "Dutch", "pl": "Polish", "hi": "Hindi",
}
