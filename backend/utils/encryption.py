"""Secure API-key storage backed by the OS credential store (Windows
Credential Manager via `keyring`). Keys never touch settings.json or logs."""
from __future__ import annotations

import keyring
import keyring.errors

from backend.config import KEYRING_SERVICE, LEGACY_KEYRING_SERVICE
from backend.utils.logger import get_logger

log = get_logger(__name__)

# Every provider id ever stored under the keyring service name, used only to
# migrate keys once from the pre-rename (WhisperType) service — see
# migrate_legacy_keys().
_KNOWN_PROVIDER_IDS = ("openai", "anthropic", "gemini", "openrouter", "ollama",
                       "lmstudio", "custom", "groq", "groq_backup")


def set_api_key(provider: str, key: str) -> bool:
    try:
        if key:
            keyring.set_password(KEYRING_SERVICE, provider, key)
        else:
            delete_api_key(provider)
        return True
    except keyring.errors.KeyringError:
        log.exception("Failed to store API key for %s", provider)
        return False


def get_api_key(provider: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, provider)
    except keyring.errors.KeyringError:
        log.exception("Failed to read API key for %s", provider)
        return None


def delete_api_key(provider: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, provider)
    except keyring.errors.KeyringError:
        pass  # nothing stored


def has_api_key(provider: str) -> bool:
    return bool(get_api_key(provider))


def migrate_legacy_keys() -> None:
    """One-time copy of API keys from the pre-rename keyring service
    (WhisperType) to the current one (WhisperText). Safe to call on every
    startup — skips any provider that's already set under the new name."""
    for provider in _KNOWN_PROVIDER_IDS:
        try:
            if get_api_key(provider):
                continue  # already migrated, or already configured fresh
            legacy_value = keyring.get_password(LEGACY_KEYRING_SERVICE, provider)
            if legacy_value:
                keyring.set_password(KEYRING_SERVICE, provider, legacy_value)
                log.info("Migrated API key for %s from legacy keyring entry", provider)
        except keyring.errors.KeyringError:
            continue
