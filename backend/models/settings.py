"""Typed settings model. Persisted as human-readable JSON; API keys go to keyring."""
from __future__ import annotations

import json
import threading
from typing import Literal

from pydantic import BaseModel, Field

from backend.config import SETTINGS_FILE

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
    history: HistorySettings = Field(default_factory=HistorySettings)


_lock = threading.Lock()
_settings: Settings | None = None


def load_settings() -> Settings:
    """Load settings from disk, tolerating missing or partially invalid files."""
    global _settings
    with _lock:
        if _settings is None:
            try:
                _settings = Settings.model_validate(
                    json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                _settings = Settings()
                _write(_settings)
        return _settings


def save_settings(new: Settings) -> Settings:
    global _settings
    with _lock:
        _settings = new
        _write(new)
        return new


def update_settings(patch: dict) -> Settings:
    """Deep-merge a partial dict into current settings and persist."""
    current = load_settings().model_dump()

    def merge(dst: dict, src: dict) -> dict:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v
        return dst

    return save_settings(Settings.model_validate(merge(current, patch)))


def _write(s: Settings) -> None:
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)  # atomic on same volume
