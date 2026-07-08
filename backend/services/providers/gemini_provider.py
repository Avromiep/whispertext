"""Google Gemini adapter (generativelanguage REST API)."""
from __future__ import annotations

import time

from backend.services.providers.base import AIProvider, AIResponse

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Gemini 2.x models default to "thinking" (extended internal reasoning)
# on every request, which measured ~7s of latency on a trivial grammar-fix
# call vs ~0.7s with it disabled. Grammar/punctuation cleanup never benefits
# from multi-step reasoning, so we always turn it off for this task.
_THINKING_CAPABLE_PREFIXES = ("gemini-2.5", "gemini-3")


class GeminiProvider(AIProvider):
    id = "gemini"
    display_name = "Google Gemini"

    async def generate(self, system: str, user: str) -> AIResponse:
        t0 = time.monotonic()
        generation_config: dict = {
            "temperature": self.config.temperature,
            "maxOutputTokens": self.config.max_tokens,
        }
        if self.config.model.startswith(_THINKING_CAPABLE_PREFIXES):
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}

        r = await self.client.post(
            f"{API_BASE}/models/{self.config.model}:generateContent",
            params={"key": self.api_key or ""},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": generation_config,
            })
        r.raise_for_status()
        candidates = r.json().get("candidates", [])
        if not candidates:
            raise ValueError("Gemini returned no candidates (safety block?)")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        return AIResponse(text=text, provider=self.id, model=self.config.model,
                          latency_ms=int((time.monotonic() - t0) * 1000))

    async def list_models(self) -> list[str]:
        r = await self.client.get(f"{API_BASE}/models",
                                  params={"key": self.api_key or ""})
        r.raise_for_status()
        return sorted(
            m["name"].removeprefix("models/")
            for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", []))
