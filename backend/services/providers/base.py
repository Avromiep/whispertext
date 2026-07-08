"""Unified AI provider abstraction (Part 5 of spec).

Every provider implements the same interface and returns the same response
object, so the rest of the app can switch providers without code changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from backend.models.settings import ProviderConfig


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    latency_ms: int = 0
    error: str | None = None


@dataclass
class ProviderStatus:
    id: str
    connected: bool
    message: str = ""
    models: list[str] = field(default_factory=list)
    latency_ms: int = 0


class AIProvider(ABC):
    """Interface: initialize() -> validate() -> generate()/list_models() -> shutdown()."""

    id: str = "base"
    display_name: str = "Base"
    is_local: bool = False
    needs_api_key: bool = True

    def __init__(self, config: ProviderConfig, api_key: str | None = None) -> None:
        self.config = config
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.config.timeout_s)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self.initialize()
        assert self._client is not None
        return self._client

    @abstractmethod
    async def generate(self, system: str, user: str) -> AIResponse:
        """Run a completion. Raises on failure (retry handled by LLMService)."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Query available models from the provider — never hardcoded."""

    async def validate(self) -> ProviderStatus:
        """Cheap connectivity/API-key check used by 'Test Connection'."""
        import time
        t0 = time.monotonic()
        try:
            models = await self.list_models()
            return ProviderStatus(
                id=self.id, connected=True, models=models,
                latency_ms=int((time.monotonic() - t0) * 1000))
        except httpx.HTTPStatusError as exc:
            msg = ("Invalid API key" if exc.response.status_code in (401, 403)
                   else f"HTTP {exc.response.status_code}")
            return ProviderStatus(id=self.id, connected=False, message=msg)
        except (httpx.HTTPError, OSError) as exc:
            return ProviderStatus(id=self.id, connected=False, message=str(exc))

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
