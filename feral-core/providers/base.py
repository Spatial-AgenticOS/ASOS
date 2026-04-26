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

from .model_classes import ModelClass, classify, filter_models

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

    # NOTE: ``list_models`` is intentionally kept zero-arg on the
    # Protocol to preserve structural compatibility with legacy adapters
    # (community-installed providers written against the v1 surface).
    # The chat-only filter in W24a lives on :class:`BaseProvider` as an
    # optional extension: ``BaseProvider.list_models(model_class="chat")``
    # filters via :mod:`providers.model_classes`. The ``ProviderCatalog``
    # detects the capability via ``inspect.signature`` so mixed fleets
    # (some adapters extended, some not) still work.

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

    def list_models(self, model_class: Optional[ModelClass] = None) -> list[str]:
        """Return adapter-known model ids, optionally filtered by class.

        Legacy callers pass no argument → behaviour is unchanged (the
        full, raw ``_models`` list, in the same order the adapter
        populated it).

        Callers that want the chat-only subset (the v2 Settings picker
        dropdown, the composer model-switcher) pass
        ``model_class="chat"`` and get a filtered view through
        :func:`providers.model_classes.filter_models`. The filter is
        transparent about unknown ids — a freshly-released model that
        hasn't reached the classifier yet still appears in the
        chat-class result so the user can still pick it. See the
        classifier module for the rules.

        Providers that want richer per-model narrowing (OpenRouter's
        modality-aware lookup) override :meth:`_capabilities_for_model`;
        the base implementation does not pre-filter by vision / audio /
        etc — those are additive capabilities, not model classes.
        """
        return filter_models(
            self.provider_id, list(self._models), model_class=model_class
        )

    def pricing_per_1k(self, model: str) -> dict[str, float]:
        return dict(self._pricing.get(model, {"input": 0.0, "output": 0.0}))

    def supports(self, capability: str) -> bool:
        return capability in self._capabilities

    def classify_model(self, model_id: str) -> ModelClass:
        """Classify ``model_id`` against this adapter's provider rules.

        Thin wrapper around :func:`providers.model_classes.classify` so
        callers holding an adapter instance don't have to import the
        classifier module separately.
        """
        return classify(self.provider_id, model_id)

    def _capabilities_for_model(self, model_id: str) -> set[str]:
        """Return the capabilities advertised for ``model_id``.

        The base implementation returns the provider-wide
        ``_capabilities`` set — i.e. "any capability the adapter
        advertises at all, advertise it for every id". That's the
        correct answer for single-backend providers (Anthropic,
        DeepSeek, Gemini, Groq, OpenAI) where every listed model
        supports the same surface.

        OpenRouter overrides this hook to do per-route narrowing: it's
        a router, so its ``_capabilities`` advertises the SUPERSET
        (including ``"vision"``) and ``_capabilities_for_model`` drops
        the caps the routed target doesn't support. The orchestrator
        consults this hook before deciding whether to early-return a
        ``does not support vision input`` error.
        """
        return set(self._capabilities)

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
