"""Pluggable LLM provider system.

Every supported provider (OpenAI, Anthropic, Gemini, Ollama, Groq,
DeepSeek, Moonshot/Kimi, xAI, Together, OpenRouter, Bedrock, TGI, …)
conforms to a single :class:`Provider` Protocol. This keeps the
orchestrator's inference surface branch-free and lets community-
published ``kind=provider`` registry items drop in at runtime.

The canonical model catalog lives in :mod:`providers.model_catalog` and
is refreshed by ``scripts/research_providers.py`` (run daily via a
GitHub Actions cron). User-installed community providers register by
calling :func:`register_provider` at import time.
"""

from .base import (
    ChatMessage,
    ChatResponse,
    Provider,
    register_provider,
    get_provider,
    list_providers,
)

__all__ = [
    "ChatMessage",
    "ChatResponse",
    "Provider",
    "register_provider",
    "get_provider",
    "list_providers",
]
