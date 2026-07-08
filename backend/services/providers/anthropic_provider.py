"""Anthropic Claude adapter (Messages API)."""
from __future__ import annotations

import time

from backend.services.providers.base import AIProvider, AIResponse

API_BASE = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    id = "anthropic"
    display_name = "Anthropic Claude"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key or "",
            "anthropic-version": API_VERSION,
            "Content-Type": "application/json",
        }

    async def generate(self, system: str, user: str) -> AIResponse:
        t0 = time.monotonic()
        r = await self.client.post(
            f"{API_BASE}/messages",
            headers=self._headers(),
            json={
                "model": self.config.model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            })
        r.raise_for_status()
        blocks = r.json()["content"]
        text = "".join(b["text"] for b in blocks if b["type"] == "text").strip()
        return AIResponse(text=text, provider=self.id, model=self.config.model,
                          latency_ms=int((time.monotonic() - t0) * 1000))

    async def list_models(self) -> list[str]:
        r = await self.client.get(f"{API_BASE}/models", headers=self._headers())
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]
