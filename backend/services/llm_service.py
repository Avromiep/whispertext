"""AI cleanup stage: prompt presets, provider registry, retry + hybrid fallback.

Guarantee: the user never loses a transcription. If every provider fails (or
AI cleanup is disabled / offline-only with no local model), the raw Whisper
text is returned unchanged.
"""
from __future__ import annotations

import httpx

from backend.models.settings import ProviderConfig, Settings, load_settings
from backend.services.providers.anthropic_provider import AnthropicProvider
from backend.services.providers.base import AIProvider, AIResponse, ProviderStatus
from backend.services.providers.gemini_provider import GeminiProvider
from backend.services.providers.ollama_provider import OllamaProvider
from backend.services.providers.openai_compat import (
    CustomEndpointProvider, LMStudioProvider, OpenAICompatProvider,
    OpenRouterProvider)
from backend.utils.encryption import get_api_key, has_api_key
from backend.utils.logger import get_logger
from backend.utils.retry import retry_async

log = get_logger(__name__)

PROVIDER_CLASSES: dict[str, type[AIProvider]] = {
    "openai": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "lmstudio": LMStudioProvider,
    "custom": CustomEndpointProvider,
}

# --------------------------------------------------------------------- prompts
_BASE_RULES = (
    "You are a dictation editor. Fix grammar, punctuation, and capitalization. "
    "Remove filler words and false starts. Never change the meaning, never add "
    "information, never summarize, never answer questions in the text. "
    "Return ONLY the corrected text with no preamble or quotes.")

PROMPT_PRESETS: dict[str, dict[str, str]] = {
    "professional": {
        "label": "Professional",
        "description": "Polished business tone for emails and documents.",
        "prompt": _BASE_RULES + " Use a clear, professional business tone.",
    },
    "friendly": {
        "label": "Friendly",
        "description": "Natural, casual tone for chats and texts.",
        "prompt": _BASE_RULES + " Keep the tone casual and natural, like friendly texting.",
    },
    "executive": {
        "label": "Executive",
        "description": "Concise, confident, action-oriented phrasing.",
        "prompt": _BASE_RULES + " Prefer concise, confident, action-oriented phrasing.",
    },
    "technical": {
        "label": "Technical",
        "description": "Preserves code, commands, variables, and markdown exactly.",
        "prompt": _BASE_RULES + (
            " Preserve code, shell commands, variable names, file paths, and "
            "markdown syntax exactly as spoken. Format code words in backticks."),
    },
    "medical": {
        "label": "Medical",
        "description": "Never alters medical terminology or dosages.",
        "prompt": _BASE_RULES + (
            " Never alter medical terminology, drug names, or dosages. "
            "Only fix grammar and punctuation around them."),
    },
    "legal": {
        "label": "Legal",
        "description": "Preserves wording exactly; punctuation only.",
        "prompt": (
            "You are a legal dictation editor. Preserve the speaker's wording "
            "EXACTLY. Only add punctuation and capitalization. Never rephrase, "
            "remove, or reorder words. Return only the corrected text."),
    },
    "academic": {
        "label": "Academic",
        "description": "Formal scholarly style with precise wording.",
        "prompt": _BASE_RULES + " Use formal academic style with precise wording.",
    },
    "creative": {
        "label": "Creative",
        "description": "Keeps the writer's voice; light-touch fixes only.",
        "prompt": _BASE_RULES + (
            " Preserve the writer's voice and stylistic choices; make only "
            "light-touch corrections."),
    },
}

# Local models perform better with short prompts (spec: prompt optimization).
_LOCAL_PROMPT = (
    "Correct grammar and punctuation. Remove filler words. Preserve meaning. "
    "Return only the corrected text.")

_PERF_PROFILES = {
    "quality": {"temperature": 0.4, "max_tokens": 4096},
    "balanced": {"temperature": 0.3, "max_tokens": 2048},
    "speed": {"temperature": 0.1, "max_tokens": 1024},
}


def _is_transient(exc: BaseException) -> bool:
    """Retry only errors that waiting can fix. Bad API keys (4xx) and
    servers that aren't running (connect refused) fail fast so the chain
    moves on to the next provider immediately."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    if isinstance(exc, httpx.ConnectError):
        return False
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


class LLMService:
    def __init__(self) -> None:
        # provider_id -> (config signature, live instance). Reusing instances
        # keeps httpx connection pools warm, avoiding a TLS handshake per
        # dictation. Only valid while used from a single persistent loop.
        self._cache: dict[str, tuple[tuple, AIProvider]] = {}

    def _signature(self, provider_id: str, cfg: ProviderConfig, api_key: str | None) -> tuple:
        return (cfg.model, cfg.base_url, cfg.temperature, cfg.max_tokens,
                cfg.timeout_s, api_key)

    async def cached_provider(self, provider_id: str, settings: Settings) -> AIProvider:
        cls = PROVIDER_CLASSES[provider_id]
        cfg = settings.ai.providers[provider_id].model_copy(
            update=_PERF_PROFILES[settings.ai.performance])
        key = get_api_key(provider_id) if cls.needs_api_key else None
        sig = self._signature(provider_id, cfg, key)
        cached = self._cache.get(provider_id)
        if cached and cached[0] == sig:
            return cached[1]
        if cached:
            await cached[1].shutdown()
        provider = cls(cfg, api_key=key)
        provider.initialize()
        self._cache[provider_id] = (sig, provider)
        return provider

    def get_provider(self, provider_id: str, settings: Settings | None = None) -> AIProvider:
        settings = settings or load_settings()
        cls = PROVIDER_CLASSES.get(provider_id)
        if cls is None:
            raise ValueError(f"Unknown provider: {provider_id}")
        cfg = settings.ai.providers.get(provider_id)
        if cfg is None:
            raise ValueError(f"Provider not configured: {provider_id}")
        cfg = cfg.model_copy(update=_PERF_PROFILES[settings.ai.performance])
        p = cls(cfg, api_key=get_api_key(provider_id) if cls.needs_api_key else None)
        p.initialize()
        return p

    def _system_prompt(self, provider: AIProvider, settings: Settings) -> str:
        if provider.is_local:
            prompt = _LOCAL_PROMPT
        else:
            preset = PROMPT_PRESETS.get(settings.ai.preset, PROMPT_PRESETS["professional"])
            prompt = preset["prompt"]
        f = settings.formatting
        extras = []
        if f.spoken_punctuation:
            extras.append('Convert spoken punctuation ("comma", "period", '
                          '"question mark", "new paragraph") into symbols/breaks.')
        if f.spoken_lists:
            extras.append('Convert "bullet point"/"number one..." into markdown lists.')
        if f.smart_paragraphs:
            extras.append("Insert paragraph breaks at natural topic changes.")
        if settings.ai.custom_instructions.strip():
            extras.append(settings.ai.custom_instructions.strip())
        return prompt + (" " + " ".join(extras) if extras else "")

    def _provider_chain(self, settings: Settings) -> list[str]:
        """Ordered provider ids to try, honoring mode / cost / offline settings.

        Cloud providers with no stored API key are excluded up front — calling
        them can only produce a 401 and would waste time before the fallback.
        """
        ai = settings.ai
        local = [p for p in PROVIDER_CLASSES if PROVIDER_CLASSES[p].is_local]
        chain: list[str] = [ai.provider]
        if ai.mode == "hybrid":
            chain += [p for p in ai.fallback_order if p != ai.provider]
        if ai.minimize_costs:
            # Prefer local providers first when minimizing API costs.
            chain.sort(key=lambda p: 0 if p in local else 1)
        if ai.offline_only or ai.mode == "local":
            chain = [p for p in chain if p in local]
        chain = [p for p in chain
                 if not PROVIDER_CLASSES[p].needs_api_key or has_api_key(p)]
        return list(dict.fromkeys(chain))  # dedupe, keep order

    async def cleanup(self, raw_text: str) -> AIResponse:
        """Clean a transcript. Always returns a usable result (raw as last resort)."""
        settings = load_settings()
        if not raw_text.strip() or not settings.ai.enabled:
            return AIResponse(text=raw_text, provider="none", model="")

        last_error = ""
        for pid in self._provider_chain(settings):
            try:
                provider = await self.cached_provider(pid, settings)
                if not provider.config.model:
                    continue  # unconfigured (e.g. Ollama with no model chosen)
                system = self._system_prompt(provider, settings)
                result = await retry_async(
                    lambda p=provider, s=system: p.generate(s, raw_text),
                    attempts=settings.ai.retries, should_retry=_is_transient,
                    label=f"AI cleanup via {pid}")
                if result.text:
                    return result
            except Exception as exc:  # any provider failure -> try next in chain
                last_error = f"{pid}: {exc}"
                log.warning("Provider %s failed, trying next: %s", pid, exc)

        log.error("All AI providers failed (%s); returning raw transcript", last_error)
        return AIResponse(text=raw_text, provider="raw", model="",
                          error=last_error or "No AI provider available")

    async def validate_provider(self, provider_id: str) -> ProviderStatus:
        provider = self.get_provider(provider_id)
        try:
            return await provider.validate()
        finally:
            await provider.shutdown()


llm_service = LLMService()
