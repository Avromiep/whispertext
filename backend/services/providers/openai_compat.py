"""OpenAI-compatible chat-completions adapter.

Covers OpenAI, OpenRouter, LM Studio, llama.cpp server, and any custom
OpenAI-compatible endpoint — they differ only in base URL and auth header.
"""
from __future__ import annotations

import time

from backend.services.providers.base import AIProvider, AIResponse


class OpenAICompatProvider(AIProvider):
    id = "openai"
    display_name = "OpenAI"
    default_base = "https://api.openai.com/v1"

    @property
    def base_url(self) -> str:
        return (self.config.base_url or self.default_base).rstrip("/")

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate(self, system: str, user: str) -> AIResponse:
        t0 = time.monotonic()
        r = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.config.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            })
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return AIResponse(text=text, provider=self.id, model=self.config.model,
                          latency_ms=int((time.monotonic() - t0) * 1000))

    async def list_models(self) -> list[str]:
        r = await self.client.get(f"{self.base_url}/models", headers=self._headers())
        r.raise_for_status()
        return sorted(m["id"] for m in r.json().get("data", []))


class OpenRouterProvider(OpenAICompatProvider):
    id = "openrouter"
    display_name = "OpenRouter"
    default_base = "https://openrouter.ai/api/v1"


class LMStudioProvider(OpenAICompatProvider):
    id = "lmstudio"
    display_name = "LM Studio"
    default_base = "http://127.0.0.1:1234/v1"
    is_local = True
    needs_api_key = False


class CustomEndpointProvider(OpenAICompatProvider):
    id = "custom"
    display_name = "Custom OpenAI-compatible"
    default_base = "http://127.0.0.1:8080/v1"
    is_local = True
    needs_api_key = False
