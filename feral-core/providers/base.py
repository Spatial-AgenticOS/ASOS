"""The Provider Protocol + a tiny in-process registry.

Design rules
------------
* Async ``chat()`` is the only required call surface. Streaming is
  exposed as a separate ``stream_chat`` that returns an async iterator —
  implementations that can't stream should emit one chunk with the full
  response.
* ``list_models()`` is synchronous and cheap; it reads from the bundled
  model catalog (``providers/model_catalog.json``). Providers that
  need to refresh from the network do so in ``refresh_models()``.
* ``pricing_per_1k(model)`` returns ``{"input": $per_1k, "output": $per_1k}``
  so the orchestrator can pick the cheapest capable model per turn.
* ``supports(capability)`` answers boolean queries like
  ``"vision"``, ``"tool_calling"``, ``"json_mode"``, ``"audio_in"``,
  ``"audio_out"``, ``"streaming"``, ``"thinking"``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Protocol, runtime_checkable

logger = logging.getLogger("feral.providers")


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    name: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChatResponse:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)  # input_tokens, output_tokens, total_tokens
    finish_reason: str = "stop"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class Provider(Protocol):
    provider_id: str
    display_name: str

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        ...

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        ...

    def list_models(self) -> list[str]:
        ...

    def pricing_per_1k(self, model: str) -> dict[str, float]:
        ...

    def supports(self, capability: str) -> bool:
        ...

    async def refresh_models(self) -> list[str]:
        """Fetch the latest model list from the provider's /v1/models
        endpoint (or equivalent). Returns the updated list. Providers
        that can't introspect remotely fall back to ``list_models()``."""
        ...


# ─────────────────────────────────────────────────────────────
# In-process registry.
# ─────────────────────────────────────────────────────────────

_REGISTRY: dict[str, Provider] = {}


def register_provider(provider: Provider) -> None:
    """Register a provider instance. Last registration wins."""
    if not isinstance(provider, Provider):
        raise TypeError(
            f"{type(provider).__name__} does not satisfy the Provider Protocol"
        )
    _REGISTRY[provider.provider_id] = provider
    logger.info("provider registered: %s (%s)", provider.provider_id, provider.display_name)


def get_provider(provider_id: str) -> Provider:
    if provider_id not in _REGISTRY:
        raise KeyError(
            f"provider '{provider_id}' not registered. "
            f"Known: {sorted(_REGISTRY.keys())}. "
            "Install a community provider via `feral install <id>` if it's "
            "on registry.feral.sh."
        )
    return _REGISTRY[provider_id]


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())


# ─────────────────────────────────────────────────────────────
# Minimal BaseProvider — handy for subclassing.
# ─────────────────────────────────────────────────────────────


class BaseProvider:
    """Convenience base that fills in no-ops + defaults.

    Concrete providers override ``chat`` (and optionally ``stream_chat``,
    ``pricing_per_1k``, ``supports``, ``refresh_models``).
    """

    provider_id: str = "base"
    display_name: str = "Base Provider"

    _models: list[str] = []
    _pricing: dict[str, dict[str, float]] = {}
    _capabilities: set[str] = set()

    def list_models(self) -> list[str]:
        return list(self._models)

    def pricing_per_1k(self, model: str) -> dict[str, float]:
        return dict(self._pricing.get(model, {"input": 0.0, "output": 0.0}))

    def supports(self, capability: str) -> bool:
        return capability in self._capabilities

    async def refresh_models(self) -> list[str]:
        return list(self._models)

    async def stream_chat(
        self, messages: list[ChatMessage], *, model: str, **kwargs: Any
    ) -> AsyncIterator[str]:
        resp = await self.chat(messages, model=model, **kwargs)  # type: ignore[attr-defined]
        # Yield the full response as a single chunk so callers relying on
        # the iterator shape still work when streaming isn't available.
        async def _single() -> AsyncIterator[str]:
            yield resp.text

        return _single()


# Avoid an "unused" warning on asyncio if a consumer never calls stream.
_ = asyncio
