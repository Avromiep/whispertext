"""Ollama adapter using the native API (richer model listing than /v1)."""
from __future__ import annotations

import time

from backend.services.providers.base import AIProvider, AIResponse


class OllamaProvider(AIProvider):
    id = "ollama"
    display_name = "Ollama"
    is_local = True
    needs_api_key = False

    @property
    def base_url(self) -> str:
        return (self.config.base_url or "http://127.0.0.1:11434").rstrip("/")

    async def generate(self, system: str, user: str) -> AIResponse:
        t0 = time.monotonic()
        r = await self.client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.config.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "stream": False,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                },
            })
        r.raise_for_status()
        text = r.json()["message"]["content"].strip()
        return AIResponse(text=text, provider=self.id, model=self.config.model,
                          latency_ms=int((time.monotonic() - t0) * 1000))

    async def list_models(self) -> list[str]:
        r = await self.client.get(f"{self.base_url}/api/tags")
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))

    async def model_details(self) -> list[dict]:
        """Installed models with sizes, for the local model management panel."""
        r = await self.client.get(f"{self.base_url}/api/tags")
        r.raise_for_status()
        return [{"name": m["name"], "size_gb": round(m.get("size", 0) / 2**30, 2)}
                for m in r.json().get("models", [])]
