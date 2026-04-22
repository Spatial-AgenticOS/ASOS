"""ProviderCatalog — single source of truth for FERAL's LLM provider + model inventory.

Before this module existed the codebase had *three* parallel registries:

* ``providers/*.py`` adapters — rich ``refresh_models`` / pricing /
  capability code, but only imported by tests.
* ``agents/llm_provider.py::_PROVIDER_REGISTRY`` — a tuple keyed on
  provider id, used by the runtime ``LLMProvider`` for chat.
* ``cli/setup_wizard.py::PROVIDERS`` — a hardcoded dict duplicating
  model lists, used by the interactive setup flow.

The end result was that newer provider models (GPT-5, Claude 4.5, any
2026-released name) were rejected by the wizard while the adapters
already knew how to list them. This module collapses all three
registries into one catalog so the wizard, REST API, v2 `/setup`
page, and runtime ``LLMProvider`` read from the same source.

Responsibilities
----------------
* Keep one adapter instance per provider id. API keys / base URLs are
  re-bound through :meth:`configure` when the caller supplies fresh
  credentials — no process restart required.
* Serve cached model lists from ``~/.feral/.cache/model_catalog.json``
  with a 24-hour TTL so an offline ``feral setup`` still produces
  sensible defaults, and avoid hammering provider APIs on every boot.
* ``list_models(id, live=True)`` is the ergonomic call: returns the
  latest models, refreshing from the provider's ``/v1/models`` (or
  equivalent) when the cache is stale and the network is reachable.
* ``probe(id)`` is the "is it ready?" check used by the wizard's
  side-by-side table — returns ``{reachable, detected_models, error}``
  in one call so both CLI and v2 Setup can render identical status.

Non-goals
---------
* No LLM inference. The existing chat code paths are unchanged;
  ``LLMProvider.chat`` continues to own the hot path. The catalog is
  strictly about *metadata* (what providers exist, what models they
  support, whether they're configured).
* No credential persistence beyond BlindVault / settings.json. The
  catalog never writes keys to disk itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .base import BaseProvider, Provider

logger = logging.getLogger("feral.providers.catalog")


# ----------------------------------------------------------------------
# Provider metadata + descriptor
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderDescriptor:
    """Static metadata the catalog needs to advertise a provider.

    Runtime properties that change (API key presence, current base URL)
    are stored on the adapter instance itself; this descriptor is the
    "type" info the wizard + settings UI render unchanged.
    """

    provider_id: str
    display_name: str
    supports_local: bool
    requires_api_key: bool
    default_base_url: str
    default_model: str
    credential_env_var: str = ""
    aliases: tuple[str, ...] = ()
    notes: str = ""


@dataclass
class ProviderStatus:
    """Live snapshot the wizard renders in its side-by-side table."""

    provider_id: str
    display_name: str
    supports_local: bool
    requires_api_key: bool
    configured: bool
    reachable: Optional[bool] = None
    default_base_url: str = ""
    default_model: str = ""
    last_refresh: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "display_name": self.display_name,
            "supports_local": self.supports_local,
            "requires_api_key": self.requires_api_key,
            "configured": self.configured,
            "reachable": self.reachable,
            "default_base_url": self.default_base_url,
            "default_model": self.default_model,
            "last_refresh": self.last_refresh,
            "error": self.error,
        }


# ----------------------------------------------------------------------
# Built-in descriptors
# ----------------------------------------------------------------------


BUILT_IN_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider_id="openai",
        display_name="OpenAI",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        credential_env_var="OPENAI_API_KEY",
        aliases=("open ai", "openai api", "gpt", "chatgpt"),
    ),
    ProviderDescriptor(
        provider_id="anthropic",
        display_name="Anthropic",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-5",
        credential_env_var="ANTHROPIC_API_KEY",
        aliases=("claude", "anthropic api"),
        notes="No public /v1/models endpoint — models curated from the bundled catalog.",
    ),
    ProviderDescriptor(
        provider_id="gemini",
        display_name="Google Gemini",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-2.5-flash",
        credential_env_var="GOOGLE_API_KEY",
        aliases=("google", "google gemini", "gemini api"),
    ),
    ProviderDescriptor(
        provider_id="groq",
        display_name="Groq",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        credential_env_var="GROQ_API_KEY",
        aliases=("groq cloud",),
    ),
    ProviderDescriptor(
        provider_id="deepseek",
        display_name="DeepSeek",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        credential_env_var="DEEPSEEK_API_KEY",
    ),
    ProviderDescriptor(
        provider_id="openrouter",
        display_name="OpenRouter",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        credential_env_var="OPENROUTER_API_KEY",
        aliases=("open router", "router"),
    ),
    ProviderDescriptor(
        provider_id="together",
        display_name="Together AI",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://api.together.xyz/v1",
        default_model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        credential_env_var="TOGETHER_API_KEY",
        aliases=("together ai",),
    ),
    ProviderDescriptor(
        provider_id="fireworks",
        display_name="Fireworks AI",
        supports_local=False,
        requires_api_key=True,
        default_base_url="https://api.fireworks.ai/inference/v1",
        default_model="accounts/fireworks/models/llama-v3p3-70b-instruct",
        credential_env_var="FIREWORKS_API_KEY",
        aliases=("fireworks ai",),
    ),
    ProviderDescriptor(
        provider_id="bedrock",
        display_name="Amazon Bedrock",
        supports_local=False,
        requires_api_key=True,
        default_base_url="",
        default_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        credential_env_var="AWS_ACCESS_KEY_ID",
        aliases=("aws bedrock", "amazon"),
        notes="Auth via AWS IAM (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY).",
    ),
    ProviderDescriptor(
        provider_id="ollama",
        display_name="Ollama (local)",
        supports_local=True,
        requires_api_key=False,
        default_base_url="http://localhost:11434",
        default_model="llama3.3",
        aliases=("local-ollama",),
    ),
)


# ----------------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------------


DEFAULT_CACHE_TTL_SECONDS = 24 * 3600


@dataclass
class CachedModelList:
    models: list[str]
    last_refresh: float
    source: str  # "live" | "cache" | "fallback"


class ProviderCatalog:
    """Holds one adapter instance per provider id + a disk-backed model cache."""

    def __init__(
        self,
        *,
        cache_path: Optional[Path] = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        descriptors: Optional[Iterable[ProviderDescriptor]] = None,
    ) -> None:
        self._descriptors: dict[str, ProviderDescriptor] = {}
        for d in descriptors or BUILT_IN_DESCRIPTORS:
            self._descriptors[d.provider_id] = d

        self._adapters: dict[str, Provider] = {}
        self._models: dict[str, CachedModelList] = {}
        self._cache_path = cache_path
        self._cache_ttl = cache_ttl_seconds
        self._lock = asyncio.Lock()
        self._load_cache()
        self._bind_builtin_adapters()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_providers(self) -> list[ProviderDescriptor]:
        return [self._descriptors[pid] for pid in sorted(self._descriptors)]

    def get_descriptor(self, provider_id: str) -> Optional[ProviderDescriptor]:
        return self._descriptors.get(provider_id)

    def resolve_alias(self, text: str) -> Optional[str]:
        """Map a user-typed string to a known provider id.

        Accepts the id itself, the display name (case-insensitive), any
        declared alias, and finally a substring match. Returns ``None``
        if the input is empty or no provider matches.
        """
        norm = (text or "").strip().lower()
        if not norm:
            return None
        for pid, desc in self._descriptors.items():
            if norm == pid:
                return pid
            if norm == desc.display_name.lower():
                return pid
            if norm in (a.lower() for a in desc.aliases):
                return pid
        # Substring fallback — match only when unambiguous so we don't
        # send "o" to openai vs openrouter vs ollama silently.
        hits = []
        for pid, desc in self._descriptors.items():
            needles = [pid, desc.display_name.lower(), *[a.lower() for a in desc.aliases]]
            if any(norm in n for n in needles):
                hits.append(pid)
        if len(hits) == 1:
            return hits[0]
        return None

    def get_adapter(self, provider_id: str) -> Optional[Provider]:
        return self._adapters.get(provider_id)

    def register_adapter(self, adapter: Provider) -> None:
        """Register or replace the adapter for an already-described provider.

        Community-installed providers can also register a new descriptor
        via :meth:`register_descriptor` first, then this method.
        """
        pid = getattr(adapter, "provider_id", "")
        if not pid:
            raise ValueError("adapter missing provider_id")
        self._adapters[pid] = adapter

    def register_descriptor(self, descriptor: ProviderDescriptor) -> None:
        self._descriptors[descriptor.provider_id] = descriptor

    def configure(
        self,
        provider_id: str,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """Re-bind an adapter with fresh credentials / base URL.

        Called by :class:`LLMProvider` when the user switches providers
        and by the REST config route when settings change at runtime.
        """
        desc = self._descriptors.get(provider_id)
        if desc is None:
            raise KeyError(f"unknown provider_id: {provider_id!r}")
        adapter = self._build_adapter(desc, api_key=api_key, base_url=base_url, **extra)
        if adapter is not None:
            self._adapters[provider_id] = adapter

    async def list_models(
        self,
        provider_id: str,
        *,
        live: bool = True,
        force: bool = False,
    ) -> CachedModelList:
        """Return models for *provider_id*.

        ``live=False`` returns the cached value without touching the
        network. ``force=True`` ignores the TTL and always refreshes.
        """
        if provider_id not in self._descriptors:
            raise KeyError(f"unknown provider_id: {provider_id!r}")
        cached = self._models.get(provider_id)
        now = time.time()
        if cached and not force and (now - cached.last_refresh) < self._cache_ttl:
            return cached
        if not live and cached:
            return cached
        async with self._lock:
            fresh = await self._refresh_models(provider_id)
            if fresh is not None:
                self._models[provider_id] = fresh
                self._save_cache()
                return fresh
        if cached:
            return cached
        return self._fallback_models(provider_id)

    async def probe(self, provider_id: str) -> ProviderStatus:
        """Try to reach the provider; return a ready/not-ready snapshot.

        Uses the adapter's ``refresh_models()`` directly so a network
        failure is distinguishable from a successful-but-empty response.
        The catalog's ``list_models()`` helper would paper over the
        failure with its fallback list, which is the wrong answer for
        a "can we reach the provider right now?" check.
        """
        desc = self._descriptors.get(provider_id)
        if desc is None:
            return ProviderStatus(
                provider_id=provider_id,
                display_name=provider_id,
                supports_local=False,
                requires_api_key=False,
                configured=False,
                reachable=False,
                error=f"unknown provider_id: {provider_id!r}",
            )
        status = self.status_for(provider_id)
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            status.reachable = False
            status.error = "provider adapter unavailable"
            return status
        try:
            models = await adapter.refresh_models()
            cleaned = [m for m in (models or []) if m]
            status.reachable = bool(cleaned)
            status.last_refresh = time.time()
            if cleaned:
                # Persist the hit so list_models can return it without
                # re-reaching out a second time.
                self._models[provider_id] = CachedModelList(
                    models=cleaned, last_refresh=status.last_refresh, source="live"
                )
                self._save_cache()
            else:
                status.error = "provider returned no models"
        except Exception as exc:
            status.reachable = False
            status.error = str(exc)
        return status

    def status_for(self, provider_id: str) -> ProviderStatus:
        desc = self._descriptors.get(provider_id)
        if desc is None:
            raise KeyError(f"unknown provider_id: {provider_id!r}")
        configured = self._is_configured(desc)
        cached = self._models.get(provider_id)
        return ProviderStatus(
            provider_id=desc.provider_id,
            display_name=desc.display_name,
            supports_local=desc.supports_local,
            requires_api_key=desc.requires_api_key,
            configured=configured,
            default_base_url=desc.default_base_url,
            default_model=desc.default_model,
            last_refresh=cached.last_refresh if cached else 0.0,
        )

    async def refresh_all(self) -> dict[str, CachedModelList]:
        out: dict[str, CachedModelList] = {}
        for pid in self._descriptors:
            try:
                out[pid] = await self.list_models(pid, live=True, force=True)
            except Exception as exc:
                logger.debug("refresh_all: %s failed: %s", pid, exc)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _bind_builtin_adapters(self) -> None:
        for desc in self._descriptors.values():
            adapter = self._build_adapter(desc)
            if adapter is not None:
                self._adapters[desc.provider_id] = adapter

    def _build_adapter(
        self,
        descriptor: ProviderDescriptor,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **extra: Any,
    ) -> Optional[Provider]:
        """Instantiate the concrete adapter class for *descriptor*.

        Returns ``None`` and logs a debug line if the adapter module is
        missing — the catalog still advertises the provider via its
        descriptor so the wizard can surface an honest "adapter
        unavailable" status instead of silently dropping it.
        """
        pid = descriptor.provider_id
        api_key = api_key if api_key is not None else self._env_api_key(descriptor)
        base_url = base_url or descriptor.default_base_url or None
        try:
            if pid == "openai":
                from .openai_provider import OpenAIProvider
                return OpenAIProvider(api_key=api_key, base_url=base_url)
            if pid == "anthropic":
                from .anthropic_provider import AnthropicProvider
                return AnthropicProvider(api_key=api_key, base_url=base_url)
            if pid == "gemini":
                from .gemini_provider import GeminiProvider
                return GeminiProvider(api_key=api_key, base_url=base_url)
            if pid == "groq":
                from .groq_provider import GroqProvider
                return GroqProvider(api_key=api_key, base_url=base_url)
            if pid == "deepseek":
                from .deepseek_provider import DeepSeekProvider
                return DeepSeekProvider(api_key=api_key, base_url=base_url)
            if pid == "openrouter":
                from .openrouter_provider import OpenRouterProvider
                return OpenRouterProvider(api_key=api_key, base_url=base_url)
            if pid == "together":
                from .together_provider import TogetherProvider
                return TogetherProvider(api_key=api_key, base_url=base_url)
            if pid == "fireworks":
                from .fireworks_provider import FireworksProvider
                return FireworksProvider(api_key=api_key, base_url=base_url)
            if pid == "bedrock":
                from .bedrock_provider import BedrockProvider
                return BedrockProvider(
                    region=extra.get("region") or os.environ.get("AWS_REGION"),
                    aws_access_key_id=extra.get("aws_access_key_id") or api_key,
                    aws_secret_access_key=extra.get("aws_secret_access_key")
                    or os.environ.get("AWS_SECRET_ACCESS_KEY"),
                    aws_session_token=extra.get("aws_session_token")
                    or os.environ.get("AWS_SESSION_TOKEN"),
                )
            if pid == "ollama":
                from .ollama_provider import OllamaProvider
                return OllamaProvider(base_url=base_url)
            if pid == "lmstudio":
                from .lmstudio_provider import LMStudioProvider
                return LMStudioProvider(base_url=base_url)
        except ImportError as exc:
            logger.debug("adapter import for %s failed: %s", pid, exc)
            return None
        logger.debug("no known adapter class for provider_id=%s", pid)
        return None

    async def _refresh_models(self, provider_id: str) -> Optional[CachedModelList]:
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            return None
        try:
            models = await adapter.refresh_models()
        except Exception as exc:
            logger.debug("refresh_models(%s) raised: %s", provider_id, exc)
            return None
        cleaned = [m for m in (models or []) if m]
        if not cleaned:
            # Distinguish "provider returned nothing" from "network error"
            # by falling back to the adapter's synchronous cache — still
            # better than an empty list.
            try:
                cleaned = list(adapter.list_models() or [])
            except Exception:
                cleaned = []
        if not cleaned:
            return None
        return CachedModelList(
            models=cleaned, last_refresh=time.time(), source="live"
        )

    def _fallback_models(self, provider_id: str) -> CachedModelList:
        adapter = self._adapters.get(provider_id)
        models: list[str] = []
        if adapter is not None:
            try:
                models = list(adapter.list_models() or [])
            except Exception:
                models = []
        return CachedModelList(models=models, last_refresh=0.0, source="fallback")

    def _env_api_key(self, descriptor: ProviderDescriptor) -> Optional[str]:
        if not descriptor.credential_env_var:
            return None
        return os.environ.get(descriptor.credential_env_var) or None

    def _is_configured(self, descriptor: ProviderDescriptor) -> bool:
        if not descriptor.requires_api_key:
            return True
        return bool(self._env_api_key(descriptor))

    def _load_cache(self) -> None:
        if self._cache_path is None:
            return
        try:
            if not self._cache_path.is_file():
                return
            raw = json.loads(self._cache_path.read_text())
        except Exception as exc:
            logger.debug("catalog cache read failed: %s", exc)
            return
        for pid, blob in (raw.get("providers") or {}).items():
            try:
                self._models[pid] = CachedModelList(
                    models=list(blob.get("models") or []),
                    last_refresh=float(blob.get("last_refresh") or 0),
                    source=str(blob.get("source") or "cache"),
                )
            except Exception:
                continue

    def _save_cache(self) -> None:
        if self._cache_path is None:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "providers": {
                pid: {
                    "models": cached.models,
                    "last_refresh": cached.last_refresh,
                    "source": cached.source,
                }
                for pid, cached in self._models.items()
            },
        }
        try:
            self._cache_path.write_text(json.dumps(payload, indent=2))
        except OSError as exc:
            logger.debug("catalog cache write failed: %s", exc)


# ----------------------------------------------------------------------
# Module-level factory used by api.state + cli.setup
# ----------------------------------------------------------------------


_SHARED: Optional[ProviderCatalog] = None


def default_cache_path() -> Path:
    """~/.feral/.cache/model_catalog.json."""
    try:
        from config.loader import feral_home
    except Exception:
        feral_home = lambda: Path.home() / ".feral"  # type: ignore[assignment]
    return feral_home() / ".cache" / "model_catalog.json"


def get_shared_catalog() -> ProviderCatalog:
    """Return the process-wide :class:`ProviderCatalog` singleton.

    The brain's :mod:`api.state` wires one on boot; CLI tools that
    don't go through the brain (offline ``feral setup``) use this
    factory so the wizard and brain boot the same adapter inventory.
    """
    global _SHARED
    if _SHARED is None:
        _SHARED = ProviderCatalog(cache_path=default_cache_path())
    return _SHARED


def reset_shared_catalog() -> None:
    """Test helper: drop the singleton so a new instance loads on next get."""
    global _SHARED
    _SHARED = None


# Silence unused-import warnings in static analysis
_ = contextlib, BaseProvider
