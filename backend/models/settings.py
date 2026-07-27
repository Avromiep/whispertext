"""Typed settings model. Persisted as human-readable JSON; API keys go to keyring."""
from __future__ import annotations

import json
import threading
import time
from typing import Literal

from pydantic import BaseModel, Field

from backend.config import APP_DIR, SETTINGS_FILE

# Keep a rolling history of recent settings files. Settings are tiny and rarely
# written, so this is cheap insurance against an accidental change (a bad write,
# a stale process, a mistaken edit) silently wiping user data like the custom
# vocabulary — the previous version is always recoverable from here.
SETTINGS_BACKUP_DIR = APP_DIR / "backups"
SETTINGS_BACKUP_KEEP = 30

Theme = Literal["dark", "light", "system"]
AIMode = Literal["cloud", "local", "hybrid"]
PerfProfile = Literal["quality", "balanced", "speed"]
TypingMethod = Literal["auto", "keystrokes", "clipboard"]


class HotkeySettings(BaseModel):
    # Hold Win+Shift for push-to-talk (spec-required default binding).
    push_to_talk: str = "windows+shift"
    # Double-tap Right Ctrl toggles hands-free mode (spec-required default).
    toggle_key: str = "right ctrl"
    double_tap_window_ms: int = 350
    open_settings: str = "ctrl+alt+w"
    hands_free_enabled: bool = True
    # Hands-free ends itself when you stop talking, so there's no need to
    # double-tap again. Off falls back to manual double-tap-to-stop only.
    hands_free_auto_stop: bool = True
    # Trailing silence (ms) after speech that ends a hands-free dictation.
    hands_free_silence_ms: int = 2000


class AudioSettings(BaseModel):
    input_device: int | None = None          # None = system default
    sample_rate: int = 16000
    noise_suppression: bool = True
    auto_gain: bool = True
    silence_trimming: bool = True
    vad_enabled: bool = False


class WhisperSettings(BaseModel):
    model: str = "small"
    language: str = "auto"
    compute_device: Literal["auto", "cuda", "cpu"] = "auto"
    # Greedy decoding: ~2-3x faster than beam 5 on CPU, near-identical
    # accuracy for short dictation utterances.
    beam_size: int = 1
    # "local" = faster-whisper on this machine's CPU/GPU. "groq" = Groq's
    # hosted Whisper (purpose-built inference hardware, ~200-300x real-time),
    # matching the speed of cloud dictation apps. Falls back to local
    # automatically if the cloud call fails for any reason.
    engine: Literal["local", "groq"] = "local"
    groq_model: str = "whisper-large-v3-turbo"


class ProviderConfig(BaseModel):
    model: str = ""
    base_url: str = ""                       # for ollama / lmstudio / custom endpoints
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout_s: float = 20.0


class AISettings(BaseModel):
    enabled: bool = False
    mode: AIMode = "hybrid"
    provider: str = "openai"                 # active provider id
    fallback_order: list[str] = Field(
        default_factory=lambda: ["ollama", "openai", "gemini", "openrouter"])
    preset: str = "professional"
    custom_instructions: str = ""
    performance: PerfProfile = "balanced"
    minimize_costs: bool = False
    offline_only: bool = False
    streaming: bool = False
    retries: int = 3
    providers: dict[str, ProviderConfig] = Field(default_factory=lambda: {
        "openai": ProviderConfig(model="gpt-4o-mini"),
        "anthropic": ProviderConfig(model="claude-haiku-4-5-20251001"),
        "gemini": ProviderConfig(model="gemini-2.5-flash"),
        "openrouter": ProviderConfig(model="meta-llama/llama-3.3-70b-instruct"),
        "ollama": ProviderConfig(base_url="http://127.0.0.1:11434"),
        "lmstudio": ProviderConfig(base_url="http://127.0.0.1:1234/v1"),
        "custom": ProviderConfig(),
    })


class TypingSettings(BaseModel):
    method: TypingMethod = "auto"
    chars_per_second: int = 250              # keystroke simulation speed
    instant_paste_threshold: int = 200       # chars; longer text auto-switches to paste
    pre_type_delay_ms: int = 30
    restore_clipboard: bool = True


class FormattingSettings(BaseModel):
    auto_capitalize: bool = True
    auto_punctuate: bool = True
    remove_fillers: bool = True
    smart_paragraphs: bool = True
    spoken_punctuation: bool = True          # "comma" -> "," / "new paragraph" -> \n\n
    spoken_lists: bool = True                # "bullet point" -> "- "


class VocabularySettings(BaseModel):
    # Custom words/phrases: bias the speech model toward them, and force each
    # to its exact spelling/casing in the output (e.g. "GitHub", "kubectl").
    words: list[str] = Field(default_factory=list)


class HistorySettings(BaseModel):
    enabled: bool = True
    retention_days: int = 30                 # 0 = keep forever


class GeneralSettings(BaseModel):
    theme: Theme = "light"  # "light" is the warm tan palette matching the overlay
    launch_on_boot: bool = False
    notifications: bool = True
    telemetry: bool = False
    auto_update: bool = True
    debug_mode: bool = False
    onboarding_complete: bool = False
    font_scale: float = 1.0


class Settings(BaseModel):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    hotkeys: HotkeySettings = Field(default_factory=HotkeySettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    whisper: WhisperSettings = Field(default_factory=WhisperSettings)
    ai: AISettings = Field(default_factory=AISettings)
    typing: TypingSettings = Field(default_factory=TypingSettings)
    formatting: FormattingSettings = Field(default_factory=FormattingSettings)
    vocabulary: VocabularySettings = Field(default_factory=VocabularySettings)
    history: HistorySettings = Field(default_factory=HistorySettings)


# Reentrant: update_settings holds the lock while calling load_settings.
_lock = threading.RLock()
_settings: Settings | None = None
_loaded_mtime: float | None = None


def _file_mtime() -> float | None:
    try:
        return SETTINGS_FILE.stat().st_mtime
    except OSError:
        return None


def load_settings() -> Settings:
    """Return current settings, re-reading the file if it changed on disk.

    The cache is refreshed whenever the file's mtime differs from what we last
    loaded, so a settings change written by another process (or a hand edit)
    is picked up instead of being silently overwritten by a stale cache."""
    global _settings, _loaded_mtime
    with _lock:
        mtime = _file_mtime()
        if _settings is None or mtime != _loaded_mtime:
            try:
                _settings = Settings.model_validate(
                    json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
                _loaded_mtime = mtime
            except (OSError, ValueError):
                if _settings is None:      # no readable file yet — seed defaults
                    _settings = Settings()
                    _write(_settings)
                    _loaded_mtime = _file_mtime()
        return _settings


def save_settings(new: Settings) -> Settings:
    global _settings, _loaded_mtime
    with _lock:
        _settings = new
        _write(new)
        _loaded_mtime = _file_mtime()      # our own write is the current state
        return new


def update_settings(patch: dict) -> Settings:
    """Deep-merge a partial dict into current settings and persist."""

    def merge(dst: dict, src: dict) -> dict:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v
        return dst

    with _lock:
        # Merge onto the freshest on-disk state (load_settings re-reads if the
        # file changed), so a concurrent writer's changes are never clobbered.
        current = load_settings().model_dump()
        return save_settings(Settings.model_validate(merge(current, patch)))


def _write(s: Settings) -> None:
    _backup_current()  # snapshot the existing file before we overwrite it
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)  # atomic on same volume


def _backup_current() -> None:
    """Copy the current settings file into the backups folder before it's
    overwritten, keeping the most recent SETTINGS_BACKUP_KEEP versions. Best
    effort: a backup failure must never block saving settings."""
    try:
        if not SETTINGS_FILE.exists():
            return
        current = SETTINGS_FILE.read_bytes()
        SETTINGS_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        existing = sorted(SETTINGS_BACKUP_DIR.glob("settings-*.json"))
        if existing and existing[-1].read_bytes() == current:
            return  # unchanged since the last backup — nothing new to keep
        dest = SETTINGS_BACKUP_DIR / f"settings-{time.strftime('%Y%m%d-%H%M%S')}.json"
        n = 0
        while dest.exists():  # avoid collisions within the same second
            n += 1
            dest = SETTINGS_BACKUP_DIR / f"settings-{time.strftime('%Y%m%d-%H%M%S')}-{n}.json"
        dest.write_bytes(current)
        for old in sorted(SETTINGS_BACKUP_DIR.glob("settings-*.json"))[:-SETTINGS_BACKUP_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
