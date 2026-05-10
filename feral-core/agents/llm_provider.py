"""
FERAL LLM Provider — Pluggable AI Backend
=====================================================
Supports: OpenAI API, Ollama (local), LM Studio (local),
and any OpenAI-compatible endpoint.
Now with streaming support for real-time token delivery.
"""

from __future__ import annotations
import asyncio
import os
import json
import logging
import time
import httpx
from typing import Any, Optional, AsyncGenerator

from config.loader import feral_data_home
from config.runtime import ollama_base_url, ollama_openai_base_url
from agents.chat_sanitizer import sanitize_assistant_display_text

# W3-A15: failover/retry, reasoning request-body shaping, and Anthropic
# transcript shaping live in focused sibling modules. They are imported
# (and re-exported below) so the public API of ``agents.llm_provider``
# is unchanged for existing callers and tests.
from agents.llm_failover import (
    MAX_RETRIES,
    RETRY_DELAYS,
    RETRY_AFTER_MAX_INLINE_SLEEP,
    RETRY_AFTER_MAX_COOLDOWN,
    _RETRIABLE_CODES,
    _SSE_KEEPALIVE_PREFIXES,
    _retry_llm_call,
    parse_retry_after,
    FailoverReason,
    classify_error,
    _describe_http_status_error,
    _describe_error,
    _chat_completions_model_guard,
    ProviderCooldownTracker,
)

# When the failover loop has more than one viable candidate, we cap
# same-provider retries to a single fast attempt. The historical
# 3 × [1, 2, 4]s policy meant up to 7s of dead air on a transient 5xx
# before *any* fallback got tried. With multiple candidates available,
# spending that budget on a known-bad provider is the wrong trade.
_FAILOVER_FAST_MAX_RETRIES = 2
_FAILOVER_FAST_DELAYS: list[float] = [0.5]
from agents.llm_reasoning import (
    _apply_openai_reasoning_fork,
    _apply_deepseek_reasoning_fork,
    _apply_gemini_reasoning_fork,
    _apply_anthropic_reasoning_fork,
    _apply_groq_reasoning_fork,
    apply_reasoning_fork,
)
from agents.llm_anthropic_shape import (
    _ANTHROPIC_THINKING_RESPONSE_ROOM,
    _convert_messages_for_anthropic,
    _enforce_anthropic_thinking_max_tokens,
)

logger = logging.getLogger("feral.llm")


def _gemini_api_key() -> str | None:
    """Return Gemini API key. Prefers GEMINI_API_KEY; falls back to GOOGLE_API_KEY."""
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


VISION_READY_OLLAMA_MODELS = (
    "llava",
    "moondream",
    "qwen2-vl",
    "minicpm-v",
    "bakllava",
    "gemma3",
)




def _openrouter_route_supports_vision(model: str) -> tuple[bool, str]:
    """Check whether the selected OpenRouter route handles vision.

    When the router catalog has a capability snapshot for *model* we
    consult it. Otherwise we trust the router-level superset (which
    now includes vision) and return True — sending an image to a
    non-vision route will still 400 upstream, but that's a targeted
    error instead of our old "openrouter does not support vision"
    blanket ban.
    """
    try:
        from providers.catalog import get_shared_catalog
        catalog = get_shared_catalog()
        adapter = catalog.get_adapter("openrouter")
    except Exception:
        adapter = None
    if adapter is None:
        return True, ""
    caps_for = getattr(adapter, "_capabilities_for_model", None)
    if callable(caps_for) and model:
        caps = set(caps_for(model) or ())
        if caps and "vision" not in caps:
            return False, (
                f"Selected OpenRouter route {model!r} does not accept image "
                "inputs. Pick a vision-capable route (e.g. "
                "'anthropic/claude-opus-4-7', 'openai/gpt-5.5', "
                "'google/gemini-3.1-pro')."
            )
    return True, ""

# Empty ``model`` strings tell ``apply_preset`` → ``switch_provider``
# to resolve the default via the shared catalog (Roadmap §3.5 P0).
# Hardcoding a frontier name here drifts every quarter — the catalog
# does not.
LLM_PRESETS = {
    "ollama_text": {
        "provider": "ollama",
        "model": "",
        "description": "Local text path on Ollama (uses first installed text model)",
        "vision_supported": False,
    },
    "ollama_vision": {
        "provider": "ollama",
        "model": "llava",
        "description": "Local vision path on Ollama VLM",
        "vision_supported": True,
    },
    "openai_default": {
        "provider": "openai",
        "model": "",
        "description": "Cloud default for balanced latency/quality",
        "vision_supported": True,
    },
}



# Per-provider HTTP base URL + credential env var. Default model used to
# live in this tuple — it has been stripped because hardcoded model
# literals here drift the moment a provider ships a new frontier name
# (Roadmap §3.5 P0). The runtime now resolves the default model lazily
# through ``get_shared_catalog().default_model_for(pid)`` (see
# ``_default_model_for``) so the catalog's bundled / live model list is
# the single source of truth.
_PROVIDER_REGISTRY: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "anthropic": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "kimi": ("https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "lmstudio": ("http://localhost:1234/v1", ""),
}


# Catalog id ↔ legacy llm_provider id. The catalog only knows
# "anthropic", "moonshot" etc. but llm_provider historically used
# "anthropic", "kimi" — keep this map small and explicit so no caller
# has to remember the translation.
_CATALOG_PROVIDER_MAP: dict[str, str] = {
    "kimi": "moonshot",
}


# Canonical set of provider ids the runtime can actually execute chat
# calls against. This is the single source of truth consulted by
# ``_get_provider_config``, ``switch_provider``, ``__init__``,
# ``health_snapshot`` and ``is_available`` so unknown provider ids
# (catalog-registered descriptors without a runtime binding, user
# typos, deprecated aliases) can never silently masquerade as OpenAI
# at request time. Previously every one of those call sites had its
# own implicit ``... or OPENAI defaults`` branch — removing that
# fallback is the whole point of this module-level constant.
SUPPORTED_RUNTIME_PROVIDERS: frozenset[str] = frozenset({
    *_PROVIDER_REGISTRY.keys(),  # cloud + lmstudio from the registry
    "ollama",                    # local, base url derived dynamically
    "local",                     # on-device inference engine
    "hybrid",                    # local + cloud splitter
})


def is_supported_runtime_provider(provider_name: str) -> bool:
    """True when *provider_name* has a runtime binding in this module.

    The check is intentionally narrower than ``ProviderCatalog`` —
    the catalog exposes every descriptor the UI can render (e.g.
    ``bedrock``, ``together``, ``fireworks``), but those providers
    have no OpenAI-compatible runtime adapter here yet. Returning
    False keeps the runtime from silently dialling OpenAI for them.
    """
    return (provider_name or "") in SUPPORTED_RUNTIME_PROVIDERS


def _default_model_for(provider_name: str) -> str:
    """Return the catalog's current default model id for *provider_name*.

    Returns ``""`` when the catalog is unavailable or the provider is
    unknown. Callers MUST NOT substitute a hardcoded literal — surface
    the empty string back to the user / settings UI so the picker
    renders an honest "no model selected" state instead of a stale
    guess like ``gpt-4o-mini``. The roadmap §3.5 P0 ban on hardcoded
    defaults exists because those literals went stale every quarter
    and shipped to production unnoticed.
    """
    pid = _CATALOG_PROVIDER_MAP.get(provider_name, provider_name)
    try:
        from providers.catalog import get_shared_catalog
        return get_shared_catalog().default_model_for(pid) or ""
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("_default_model_for(%s) failed: %s", provider_name, exc)
        return ""


def _cooldown_state_path() -> str:
    """Path used to persist provider cooldown circuit state."""
    override = os.environ.get("FERAL_LLM_COOLDOWN_STATE_PATH", "").strip()
    if override:
        return override
    try:
        base = feral_data_home()
        base.mkdir(parents=True, exist_ok=True)
        return str(base / "llm_provider_cooldowns.json")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("cooldown state path unavailable: %s", exc)
        return ""


class LLMProvider:
    """
    Pluggable LLM interface.
    
    Supports:
    - OpenAI API (GPT-4o, GPT-4o-mini)
    - Ollama local (llama3, mistral, etc.)
    - Any OpenAI-compatible endpoint (Groq, Together, etc.)
    - Local on-device inference (MLX on Apple Silicon, llama.cpp elsewhere)
    - Hybrid mode (local for routing, cloud for reasoning)
    """

    def __init__(self):
        self.provider = os.getenv("FERAL_LLM_PROVIDER", "openai")
        # Resolve the default model lazily from the shared
        # ``ProviderCatalog`` rather than burning a literal here. The
        # catalog reads ``model_catalog.json`` + each adapter's bundled
        # list, so this picks up frontier IDs (gpt-5.5, claude-opus-4-7,
        # gemini-3.1-pro-preview) without an llm_provider.py edit. If
        # the catalog hasn't booted yet (offline ``feral setup``,
        # tests), fall back to the env override or empty so the picker
        # surfaces an honest "choose a model" state.
        self.model = os.getenv("FERAL_LLM_MODEL", "") or _default_model_for(self.provider)
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("FERAL_LLM_BASE_URL", "")
        self.available = True
        self._config: dict = {}
        self._cooldown = ProviderCooldownTracker(storage_path=_cooldown_state_path())
        self._last_budget_routing: dict[str, Any] = {}

        # When `chat()` (the direct path, not chat_with_failover) sees a
        # permanent auth failure for a provider+key combination, we
        # remember it so subsequent calls short-circuit instead of
        # hammering the API and spamming ERROR-level logs every minute.
        # Cleared by `switch_provider()` (which is what /api/config/credentials
        # calls when the user updates their key in Settings).
        self._auth_permanent_until: dict[str, float] = {}
        self._auth_permanent_logged: set[str] = set()

        # Local inference engine (for provider=local or hybrid)
        self._local_engine = None
        self._hybrid_cloud_provider = None

        if self.provider in ("local", "hybrid"):
            self._init_local_engine()
            if self.provider == "hybrid":
                self._init_hybrid_cloud()
            if self._local_engine:
                logger.info(f"LLM Provider: {self.provider} | Local Model: {self._local_engine.model_id}")
                return
            else:
                logger.warning("Local engine init failed, falling back to cloud")
                self.provider = "openai"

        # Set defaults based on provider. Model defaults always come
        # from the catalog (`_default_model_for`) so frontier IDs land
        # without code edits.
        if self.provider == "ollama":
            self.base_url = self.base_url or ollama_openai_base_url()
            # Ollama exposes the loaded model list via /api/tags; the
            # detected name in __init__ is preferred. Fall back only if
            # the user shipped no model.
            self.model = self.model or _default_model_for("ollama")
            self.api_key = "ollama"
        elif self.provider == "groq":
            self.base_url = self.base_url or "https://api.groq.com/openai/v1"
            self.api_key = os.getenv("GROQ_API_KEY", self.api_key)
            self.model = self.model or _default_model_for("groq")
        elif self.provider == "anthropic":
            self.base_url = self.base_url or "https://api.anthropic.com/v1"
            self.api_key = os.getenv("ANTHROPIC_API_KEY", self.api_key)
            self.model = self.model or _default_model_for("anthropic")
        elif self.provider == "gemini":
            self.base_url = self.base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
            self.api_key = _gemini_api_key() or self.api_key
            self.model = self.model or _default_model_for("gemini")
        elif self.provider == "openrouter":
            self.base_url = self.base_url or "https://openrouter.ai/api/v1"
            self.api_key = os.getenv("OPENROUTER_API_KEY", self.api_key)
            self.model = self.model or _default_model_for("openrouter")
        elif self.provider == "deepseek":
            self.base_url = self.base_url or "https://api.deepseek.com"
            self.api_key = os.getenv("DEEPSEEK_API_KEY", self.api_key)
            self.model = self.model or _default_model_for("deepseek")
        elif self.provider == "kimi":
            self.base_url = self.base_url or "https://api.moonshot.cn/v1"
            self.api_key = os.getenv("MOONSHOT_API_KEY", self.api_key)
            self.model = self.model or _default_model_for("kimi")
        elif self.provider == "qwen":
            self.base_url = self.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            self.api_key = os.getenv("DASHSCOPE_API_KEY", self.api_key)
            self.model = self.model or _default_model_for("qwen")
        elif self.provider == "lmstudio":
            self.base_url = self.base_url or "http://localhost:1234/v1"
            self.api_key = "lm-studio"
            self.model = self.model or _default_model_for("lmstudio")
        elif self.provider == "openai":
            # Default path. Previously this case rode the else branch
            # that also served as the silent fallback for unknown
            # provider ids — that's the conflation W1 A3 is untangling.
            # Splitting ``openai`` into its own branch lets the else
            # below report unknown provider ids truthfully.
            self.base_url = self.base_url or "https://api.openai.com/v1"
            self.api_key = os.getenv("OPENAI_API_KEY", self.api_key)
            self.model = self.model or _default_model_for("openai")
        else:
            # Unknown provider id. Previously this branch silently
            # defaulted to ``https://api.openai.com/v1`` with the
            # inherited ``OPENAI_API_KEY`` — which meant a typo'd or
            # not-yet-supported provider id (e.g. catalog-only entries
            # like ``bedrock`` / ``together`` / ``fireworks``) would
            # masquerade as OpenAI at request time and leak the user's
            # OpenAI key to the wrong endpoint name in logs / metrics.
            # The new contract: keep the unknown provider name visible
            # to the caller, clear the inherited OpenAI key, and mark
            # the runtime unavailable unless the operator explicitly
            # set FERAL_LLM_BASE_URL for a custom OpenAI-compatible
            # gateway. Local-fallback detection below still runs.
            logger.warning(
                "Unknown LLM provider %r — no runtime adapter. "
                "Supported providers: %s. Set FERAL_LLM_PROVIDER to a "
                "supported id or supply FERAL_LLM_BASE_URL for a "
                "custom OpenAI-compatible endpoint.",
                self.provider,
                sorted(SUPPORTED_RUNTIME_PROVIDERS),
            )
            if self.base_url:
                # Operator explicitly pointed us at a custom gateway.
                # Trust it, keep the explicit api_key (if any), and
                # resolve the default model best-effort.
                self.model = self.model or _default_model_for(self.provider)
            else:
                self.base_url = ""
                self.api_key = ""
                self.model = self.model or _default_model_for(self.provider)
                self.available = False

        # Check if API key is available — if not, try local fallbacks
        if not self.api_key and self.provider not in ("ollama", "lmstudio"):
            logger.warning(f"No API key for provider '{self.provider}'. Trying local fallbacks...")
            ollama_model = self._detect_ollama()
            if ollama_model:
                self.provider = "ollama"
                self.base_url = ollama_openai_base_url()
                self.model = ollama_model
                self.api_key = "ollama"
                logger.info(f"Ollama detected — using model '{ollama_model}'")
            else:
                lmstudio_model = self._detect_lmstudio()
                if lmstudio_model:
                    self.provider = "lmstudio"
                    self.base_url = "http://localhost:1234/v1"
                    self.model = lmstudio_model
                    self.api_key = "lm-studio"
                    logger.info(f"LM Studio detected — using model '{lmstudio_model}'")
                else:
                    logger.warning(
                        "No LLM available. Set OPENAI_API_KEY or run Ollama (`ollama serve`) "
                        "or LM Studio. Brain will operate in direct-execution mode "
                        "(no reasoning, skill matching only)."
                    )
                    self.available = False
                    self.api_key = "none"

        self.client = self._build_client()

        status = "READY" if self.available else "DIRECT-EXECUTION MODE (no LLM)"
        logger.info(f"LLM Provider: {self.provider} | Model: {self.model} | Status: {status}")

    @staticmethod
    def list_presets() -> list[dict]:
        return [{"id": k, **v} for k, v in LLM_PRESETS.items()]

    def _build_client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.provider == "anthropic":
            headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=60.0)

    @staticmethod
    def _detect_ollama() -> Optional[str]:
        """Probe Ollama for running models. Returns best model name or None."""
        preferred = ["llama3.1", "llama3", "mistral", "gemma2", "phi3", "qwen2"]
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"{ollama_base_url().rstrip('/')}/api/tags", timeout=3)
            data = json.loads(resp.read())
            models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
            if not models:
                logger.info("Ollama running but no models pulled. Try: ollama pull llama3.1")
                return None
            for pref in preferred:
                if pref in models:
                    return pref
            return models[0]
        except Exception:
            return None

    @staticmethod
    def _detect_lmstudio() -> Optional[str]:
        """Probe LM Studio for loaded models. Returns model id or None."""
        try:
            import httpx
            r = httpx.get("http://localhost:1234/v1/models", timeout=2)
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    return models[0].get("id", "local-model")
        except Exception:
            pass
        return None

    def _init_local_engine(self):
        try:
            from agents.local_inference import create_local_engine
            self._local_engine = create_local_engine()
            self.available = True
        except Exception as e:
            logger.warning(f"Local LLM engine init failed: {e}")
            self._local_engine = None

    def _init_hybrid_cloud(self):
        """In hybrid mode, cloud is used for complex reasoning."""
        cloud_key = os.getenv("OPENAI_API_KEY", "")
        if cloud_key:
            self._hybrid_cloud_provider = httpx.AsyncClient(
                base_url="https://api.openai.com/v1",
                headers={"Authorization": f"Bearer {cloud_key}", "Content-Type": "application/json"},
                timeout=30.0,
            )

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict:
        """
        Send a chat completion request.
        Returns the full response dict.

        When ``fallback_providers`` is configured in ``self._config``,
        transparently delegates to :meth:`chat_with_failover` so every
        caller (digital twin, proactive, ideas engine, wherever) gains
        cross-provider failover without knowing about the distinction.
        """
        # Permanent-auth short-circuit. If a previous call established
        # that the current key is invalid (HTTP 401 + "invalid_api_key"),
        # don't keep poking the wire every 60s -- return the cached
        # error so the user gets a clear reason and the log stays quiet.
        # `switch_provider` clears the entry, so the moment the user
        # updates their key in Settings the brain starts trying again.
        # Defensive getattr because some test stubs subclass LLMProvider
        # without invoking __init__ (the cache + provider/model attrs
        # may not exist).
        auth_block_map = getattr(self, "_auth_permanent_until", None)
        if auth_block_map:
            auth_key = f"{getattr(self, 'provider', '?')}:{getattr(self, 'model', '?')}"
            auth_block = auth_block_map.get(auth_key)
            if auth_block and time.time() < auth_block:
                return {
                    "error": (
                        f"{getattr(self, 'provider', 'LLM').upper()} API key "
                        "invalid (HTTP 401). Update the key in Settings to retry."
                    ),
                    "choices": [],
                    "auth_permanent": True,
                }

        fallbacks = self._config.get("fallback_providers") if isinstance(self._config, dict) else None
        if fallbacks and not (self._local_engine and self.provider in ("local", "hybrid")):
            try:
                return await self.chat_with_failover(
                    messages, tools,
                    temperature=temperature, max_tokens=max_tokens,
                )
            except Exception as exc:
                logger.warning("chat_with_failover exhausted: %s", exc)
                return {"error": str(exc), "choices": []}

        if self._messages_contain_vision(messages):
            ok, reason = self._vision_support_status()
            if not ok:
                logger.warning(reason)
                return {"error": reason, "choices": []}

        # Guard against unsupported provider before any wire work.
        # Without this the body is assembled and POSTed against
        # whatever ``base_url`` happens to be set — which for the
        # old unknown-provider path was ``https://api.openai.com/v1``.
        if not is_supported_runtime_provider(self.provider) and self.provider not in ("local", "hybrid"):
            reason = (
                f"Selected LLM provider {self.provider!r} is not supported by this "
                f"runtime. Supported: {sorted(SUPPORTED_RUNTIME_PROVIDERS)}."
            )
            logger.warning(reason)
            return {"error": reason, "choices": []}

        model_guard_error = _chat_completions_model_guard(self.provider, self.model)
        if model_guard_error:
            logger.warning(model_guard_error)
            return {"error": model_guard_error, "choices": []}

        # Local inference path
        if self._local_engine and self.provider in ("local", "hybrid"):
            use_local = self.provider == "local" or not self._hybrid_cloud_provider
            if self.provider == "hybrid" and tools:
                use_local = False

            if use_local:
                return await self._chat_local(messages, tools, temperature, max_tokens)

        if self.provider == "anthropic":
            return await self._chat_anthropic(messages, tools, temperature, max_tokens)

        # NOTE: a previous "runtime model-class guard" lived here as a
        # belt-and-suspenders defense against the dated-transcribe-id
        # leak. Removed in 2026-05-09 audit-r8 round-2 once the actual
        # root cause was fixed at boot: `api/state.BrainState.init` now
        # calls `providers.catalog.set_shared_catalog(self.provider_catalog)`
        # so every `_default_model_for(...)` consults the live catalog
        # instead of a lazily-created empty singleton. The boot
        # self-heal + classifier are sufficient once the catalog
        # singleton is correctly wired — no per-call patching needed.

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            clean_tools = []
            for tool in tools:
                clean = {k: v for k, v in tool.items() if k != "_feral_meta"}
                clean_tools.append(clean)
            # OpenAI's /v1/chat/completions rejects payloads with more
            # than 128 tools (array_above_max_length). FERAL ships
            # 26 skills + ~23 browser endpoints + subagents + etc,
            # which overflows on some installs. We slice to 128 here
            # with a one-time warning rather than crashing the call.
            # Prioritise retention of the first tools since skills
            # register alphabetically and the brain-auto skills that
            # appear first are the hottest path.
            if self.provider in ("openai",) and len(clean_tools) > 128:
                logger.warning(
                    "openai chat/completions: truncating tools from %d → 128 "
                    "(OpenAI hard limit). Later-registered tools will not be "
                    "exposed to the model for this call.",
                    len(clean_tools),
                )
                clean_tools = clean_tools[:128]
            body["tools"] = clean_tools
            body["tool_choice"] = "auto"

        # Reasoning-family param fork: ``/v1/chat/completions`` rejects
        # ``max_tokens`` + free-form ``temperature`` on gpt-5* / o1 /
        # DeepSeek v4-pro / thinking-capable Claude / Gemini -thinking.
        # This is the exact shape of the v2026.5.0 400s in the shipped
        # terminal log (§A5 of docs/WAVE5_HARDENING_PROMPT.md).
        apply_reasoning_fork(self.provider, self.model, body)

        from observability.metrics import increment, measure
        increment("feral.llm.calls_total", attributes={"provider": self.provider, "model": self.model})
        try:
            async def _do_chat():
                resp = await self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()

            with measure("feral.llm.latency", {"provider": self.provider, "model": self.model}):
                result = await _retry_llm_call(_do_chat)
            return result
        except httpx.HTTPStatusError as e:
            increment("feral.llm.errors_total", attributes={"provider": self.provider, "model": self.model})
            detail = _describe_http_status_error(e)
            # Classify so we can short-circuit the next call instead of
            # hitting the wire every 60s when the key is dead.
            try:
                reason = classify_error(e)
            except Exception:
                reason = None
            auth_key = f"{self.provider}:{self.model}"
            if reason == FailoverReason.AUTH_PERMANENT:
                # 24h block; user updating the key in Settings clears it
                # immediately via switch_provider.
                self._auth_permanent_until[auth_key] = time.time() + 24 * 3600
                if auth_key not in self._auth_permanent_logged:
                    self._auth_permanent_logged.add(auth_key)
                    logger.error(
                        "LLM API error: %s — disabling provider until key is updated. "
                        "Open Settings and refresh the %s API key.",
                        detail, self.provider,
                    )
                else:
                    logger.debug("LLM API error (suppressed, key still invalid): %s", detail)
            else:
                logger.error("LLM API error: %s", detail)
            return {"error": detail, "choices": []}
        except Exception as e:
            increment("feral.llm.errors_total", attributes={"provider": self.provider, "model": self.model})
            detail = _describe_error(e)
            logger.error("LLM call failed: %s", detail)
            return {"error": detail, "choices": []}

    def extract_response(self, data: dict) -> tuple[Optional[str], list[dict]]:
        """
        Extract the text response and tool calls from an LLM response.
        Returns: (text_content, tool_calls)
        """
        if "error" in data or not data.get("choices"):
            return data.get("error", "No response from LLM"), []

        choice = data["choices"][0]
        message = choice.get("message", {})
        text = message.get("content", "")
        tool_calls = message.get("tool_calls", [])

        parsed_tools = []
        for tc in tool_calls:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            parsed_tools.append({
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "args": args,
            })

        return text, parsed_tools

    @staticmethod
    def _messages_contain_vision(messages: list[dict]) -> bool:
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_type = str(block.get("type", ""))
                        if block_type in ("image_url", "input_image", "image", "image_base64"):
                            return True
                        if "image_url" in block:
                            return True
            elif isinstance(content, dict):
                block_type = str(content.get("type", ""))
                if block_type in ("image_url", "input_image", "image", "image_base64"):
                    return True
                if "image_url" in content:
                    return True
        return False

    def _vision_support_status(self) -> tuple[bool, str]:
        if self.provider in ("openai", "gemini"):
            return True, ""

        # OpenRouter is a router — vision capability is per-route, not
        # per-provider. The v2026.5.0 terminal log showed this call
        # early-returning "does not support vision" on every image send
        # because the adapter's _capabilities omitted "vision". The
        # adapter fix adds vision to the superset; here we consult the
        # narrower ``_capabilities_for_model`` when the catalog knows
        # the route's modality, and otherwise trust the superset.
        if self.provider == "openrouter":
            ok, narrow_reason = _openrouter_route_supports_vision(self.model)
            if ok:
                return True, ""
            return False, narrow_reason

        # Anthropic, DeepSeek, Groq all support vision on their
        # frontier chat models; the provider registry already carries
        # that signal in the bundled ``_capabilities`` set. If we
        # ever ship a text-only Anthropic build the per-model hook
        # ``_capabilities_for_model`` narrows this.
        if self.provider in ("anthropic", "deepseek", "groq"):
            return True, ""

        if self.provider == "ollama":
            model_lower = (self.model or "").lower()
            if any(hint in model_lower for hint in VISION_READY_OLLAMA_MODELS):
                return True, ""
            return (
                False,
                "Current Ollama model does not appear vision-capable. "
                "Use a VLM model such as 'llava' or apply preset 'ollama_vision'.",
            )

        if self.provider in ("local", "hybrid") and self._local_engine:
            if getattr(self._local_engine, "supports_vision", False):
                return True, ""
            return (
                False,
                "Local inference engine is text-only and cannot process images. "
                "Use Ollama VLM for local vision (`provider=ollama`, model `llava`).",
            )

        return False, f"Provider '{self.provider}' does not support vision input."

    async def _chat_anthropic(
        self, messages: list[dict], tools: Optional[list[dict]],
        temperature: float, max_tokens: int,
    ) -> dict:
        """Anthropic Messages API → normalized to OpenAI format."""
        # A5: route OpenAI-shape transcripts through the conversion
        # helper so ``role: "tool"`` and assistant ``tool_calls`` are
        # lifted into Anthropic's content-block shape before the wire
        # request.
        system_text, conv_messages = _convert_messages_for_anthropic(messages)

        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conv_messages,
        }
        if system_text.strip():
            body["system"] = system_text.strip()

        if tools:
            anthropic_tools = []
            for t in tools:
                if t.get("type") == "function":
                    fn = t["function"]
                    anthropic_tools.append({
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
            if anthropic_tools:
                body["tools"] = anthropic_tools

        # Reasoning-family fork for Claude thinking-capable models.
        apply_reasoning_fork("anthropic", self.model, body)
        _enforce_anthropic_thinking_max_tokens(body)

        try:
            async def _do_anthropic():
                resp = await self.client.post("/messages", json=body)
                resp.raise_for_status()
                return resp.json()

            data = await _retry_llm_call(_do_anthropic)

            text_parts = []
            tool_calls = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })

            msg: dict = {"role": "assistant", "content": "\n".join(text_parts)}
            if tool_calls:
                msg["tool_calls"] = tool_calls

            return {"choices": [{"message": msg, "finish_reason": data.get("stop_reason", "end_turn")}]}
        except httpx.HTTPStatusError as e:
            detail = _describe_http_status_error(e)
            logger.error("Anthropic API error: %s", detail)
            return {"error": detail, "choices": []}
        except Exception as e:
            detail = _describe_error(e)
            logger.error("Anthropic call failed: %s", detail)
            return {"error": detail, "choices": []}

    async def _chat_local(
        self, messages: list[dict], tools: Optional[list[dict]],
        temperature: float, max_tokens: int,
    ) -> dict:
        """Run inference through the local engine."""
        try:
            if not self._local_engine.loaded:
                await self._local_engine.load_model()

            prompt = self._local_engine.format_chat(messages, tools)
            text = await self._local_engine.generate(prompt, max_tokens=max_tokens, temperature=temperature)

            clean_text, tool_calls = self._local_engine.parse_tool_calls(text)
            response_msg: dict = {"role": "assistant", "content": clean_text}

            if tool_calls:
                response_msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                    for tc in tool_calls
                ]

            return {"choices": [{"message": response_msg, "finish_reason": "stop"}]}
        except Exception as e:
            logger.error(f"Local inference failed: {e}")
            return {"error": str(e), "choices": []}

    async def _stream_via_nonstream_failover(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        *,
        primary_error: Exception,
    ) -> Optional[list[dict]]:
        """Fallback path for streaming failures.

        For providers that support cross-provider failover in non-stream
        mode, run one failover attempt and convert the response into
        stream-shaped events.
        """
        fallbacks = self._config.get("fallback_providers") if isinstance(self._config, dict) else None
        if not fallbacks:
            return None
        if self._local_engine and self.provider in ("local", "hybrid"):
            return None

        reason = classify_error(primary_error)
        # Don't hide context overflow; the caller should surface the
        # explicit model/context failure.
        if reason == FailoverReason.CONTEXT_OVERFLOW:
            return None

        try:
            self._cooldown.record_failure(self.provider, reason)
            # Prevent immediate re-probe of the same failing primary in
            # chat_with_failover's candidate loop.
            self._cooldown._last_probe[self.provider] = time.time()
        except Exception:
            pass

        logger.warning(
            "Stream primary %s/%s failed (%s); attempting non-stream failover",
            self.provider,
            self.model,
            reason.value,
        )
        try:
            result = await self.chat_with_failover(
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            primary_detail = _describe_error(primary_error)
            failover_detail = _describe_error(exc)
            logger.warning(
                "Non-stream failover attempt after stream failure exhausted: %s",
                failover_detail,
            )
            return [{
                "type": "error",
                "content": (
                    f"{primary_detail} | failover exhausted: {failover_detail}"
                ),
            }]

        if not isinstance(result, dict):
            return None
        if result.get("error"):
            return None
        if not result.get("choices"):
            return None

        text, tool_calls = self.extract_response(result)
        events: list[dict] = []
        if text:
            clean = sanitize_assistant_display_text(text)
            if clean:
                events.append({"type": "text_delta", "content": clean})
        for tc in tool_calls:
            events.append({"type": "tool_call_delta", "tool_call": tc})
        events.append({"type": "done"})
        return events

    async def chat_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a chat completion. Yields delta dicts:
          {"type": "text_delta", "content": "..."}
          {"type": "tool_call_delta", "tool_call": {...}}
          {"type": "done"}
        """
        if self._messages_contain_vision(messages):
            ok, reason = self._vision_support_status()
            if not ok:
                yield {"type": "error", "content": reason}
                return

        if not is_supported_runtime_provider(self.provider) and self.provider not in ("local", "hybrid"):
            yield {
                "type": "error",
                "content": (
                    f"Selected LLM provider {self.provider!r} is not supported by this "
                    f"runtime. Supported: {sorted(SUPPORTED_RUNTIME_PROVIDERS)}."
                ),
            }
            return

        model_guard_error = _chat_completions_model_guard(self.provider, self.model)
        if model_guard_error:
            yield {"type": "error", "content": model_guard_error}
            return

        # Local streaming path
        if self._local_engine and self.provider in ("local", "hybrid"):
            use_local = self.provider == "local" or not self._hybrid_cloud_provider
            if self.provider == "hybrid" and tools:
                use_local = False
            if use_local:
                try:
                    if not self._local_engine.loaded:
                        await self._local_engine.load_model()
                    prompt = self._local_engine.format_chat(messages, tools)
                    async for token in self._local_engine.generate_stream(prompt, max_tokens=max_tokens, temperature=temperature):
                        yield {"type": "text_delta", "content": token}
                    yield {"type": "done"}
                except Exception as e:
                    yield {"type": "error", "content": str(e)}
                return

        # Anthropic native streaming (Messages API with SSE)
        if self.provider == "anthropic":
            async for delta in self._chat_stream_anthropic(messages, tools, temperature, max_tokens):
                yield delta
            return

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            clean_tools = [{k: v for k, v in t.items() if k != "_feral_meta"} for t in tools]
            if self.provider in ("openai",) and len(clean_tools) > 128:
                # Same 128-tool hard limit as the non-streaming path.
                # See commentary in the paired site above.
                logger.warning(
                    "openai chat/completions (stream): truncating tools "
                    "from %d → 128 (OpenAI hard limit).", len(clean_tools),
                )
                clean_tools = clean_tools[:128]
            body["tools"] = clean_tools
            body["tool_choice"] = "auto"

        apply_reasoning_fork(self.provider, self.model, body)

        streamed_text = False
        stream_cm = None
        try:
            for _attempt in range(MAX_RETRIES):
                try:
                    stream_cm = self.client.stream("POST", "/chat/completions", json=body)
                    resp = await stream_cm.__aenter__()
                    resp.raise_for_status()
                    break
                except Exception as e:
                    if stream_cm:
                        try:
                            await stream_cm.__aexit__(type(e), e, e.__traceback__)
                        except Exception:
                            pass
                        stream_cm = None
                    err_str = str(e).lower()
                    retriable = any(c in err_str for c in _RETRIABLE_CODES)
                    if not retriable or _attempt == MAX_RETRIES - 1:
                        raise
                    logger.warning("LLM stream connect failed (attempt %d/%d) — retrying",
                                   _attempt + 1, MAX_RETRIES)
                    await asyncio.sleep(RETRY_DELAYS[_attempt])

            accumulated_tool_calls: dict[int, dict] = {}
            async for line in resp.aiter_lines():
                # Tolerate SSE keep-alive comment lines ("keep-alive"
                # ``: ...`` comments and empty lines). DeepSeek's
                # thinking-mode stream, OpenRouter's queue, and some
                # Anthropic variants send these during long reasoning
                # windows; treating them as termination kills the
                # stream prematurely. Per DeepSeek's 2026-04-26 docs
                # the keep-alive can run up to 10 minutes.
                if line is None or line == "" or line.startswith(":"):
                    continue
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    for _, tc in sorted(accumulated_tool_calls.items()):
                        try:
                            tc["args"] = json.loads(tc.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            tc["args"] = {}
                        yield {"type": "tool_call_delta", "tool_call": tc}
                    yield {"type": "done"}
                    return

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})

                if delta.get("content"):
                    piece = sanitize_assistant_display_text(delta["content"])
                    if piece:
                        streamed_text = True
                        yield {"type": "text_delta", "content": piece}

                for tc_delta in delta.get("tool_calls", []):
                    idx = tc_delta.get("index", 0)
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": tc_delta.get("id", ""),
                            "name": "",
                            "arguments": "",
                        }
                    entry = accumulated_tool_calls[idx]
                    func = tc_delta.get("function", {})
                    if func.get("name"):
                        entry["name"] = func["name"]
                    if func.get("arguments"):
                        entry["arguments"] += func["arguments"]
                    if tc_delta.get("id"):
                        entry["id"] = tc_delta["id"]

        except httpx.HTTPStatusError as e:
            detail = _describe_http_status_error(e)
            logger.error("LLM stream error: %s", detail)
            if not streamed_text:
                failover_events = await self._stream_via_nonstream_failover(
                    messages,
                    tools,
                    temperature,
                    max_tokens,
                    primary_error=e,
                )
                if failover_events:
                    for event in failover_events:
                        yield event
                    return
            yield {"type": "error", "content": detail}
        except Exception as e:
            detail = _describe_error(e)
            logger.error("LLM stream failed: %s", detail)
            if not streamed_text:
                failover_events = await self._stream_via_nonstream_failover(
                    messages,
                    tools,
                    temperature,
                    max_tokens,
                    primary_error=e,
                )
                if failover_events:
                    for event in failover_events:
                        yield event
                    return
            yield {"type": "error", "content": detail}
        finally:
            if stream_cm:
                try:
                    await stream_cm.__aexit__(None, None, None)
                except Exception:
                    pass

    async def _chat_stream_anthropic(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[dict, None]:
        """Native Anthropic Messages API streaming via SSE."""
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        # A5: same OpenAI → Anthropic conversion as the non-stream path.
        # Streaming previously forwarded ``role: "tool"`` as-is and
        # produced the same 400 on tool-using transcripts.
        system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)

        body: dict = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt.strip():
            body["system"] = system_prompt.strip()
        # Thinking-capable Claude models demand ``thinking`` + drop
        # ``temperature`` when streaming; adaptive (Opus 4.7) passes
        # through unchanged.
        apply_reasoning_fork("anthropic", self.model, body)
        _enforce_anthropic_thinking_max_tokens(body)
        if tools:
            body["tools"] = [
                {
                    "name": t.get("function", {}).get("name", t.get("name", "")),
                    "description": t.get("function", {}).get("description", ""),
                    "input_schema": t.get("function", {}).get("parameters", {}),
                }
                for t in tools if t.get("type") == "function" or "function" in t
            ]

        accumulated_tool_calls: dict[str, dict] = {}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=body,
                ) as resp:
                    resp.raise_for_status()
                    current_tool_id = ""
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if not data_str:
                            continue
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        if event_type == "content_block_start":
                            block = event.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool_id = block.get("id", "")
                                accumulated_tool_calls[current_tool_id] = {
                                    "id": current_tool_id,
                                    "name": block.get("name", ""),
                                    "arguments": "",
                                }

                        elif event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                piece = sanitize_assistant_display_text(delta.get("text", ""))
                                if piece:
                                    yield {"type": "text_delta", "content": piece}
                            elif delta.get("type") == "input_json_delta":
                                if current_tool_id in accumulated_tool_calls:
                                    accumulated_tool_calls[current_tool_id]["arguments"] += delta.get("partial_json", "")

                        elif event_type == "message_delta":
                            pass

                        elif event_type == "message_stop":
                            for tc in accumulated_tool_calls.values():
                                try:
                                    tc["args"] = json.loads(tc.get("arguments", "{}"))
                                except json.JSONDecodeError:
                                    tc["args"] = {}
                                yield {"type": "tool_call_delta", "tool_call": tc}
                            yield {"type": "done"}
                            return

            yield {"type": "done"}
        except httpx.HTTPStatusError as e:
            detail = _describe_http_status_error(e)
            logger.error("Anthropic stream error: %s", detail)
            yield {"type": "error", "content": detail}
        except Exception as e:
            detail = _describe_error(e)
            logger.error("Anthropic stream failed: %s", detail)
            yield {"type": "error", "content": detail}

    async def switch_provider(
        self,
        provider: str,
        model: str = "",
        api_key: str = "",
        base_url: str = "",
    ):
        """Hot-swap the LLM provider at runtime.

        ``base_url`` is an optional override; when empty, the adapter
        looks up the default base URL from :data:`_PROVIDER_REGISTRY`
        for cloud providers or the local helper for
        ``ollama`` / ``lmstudio``. The override path is what lets the
        v2 Settings page's Save-&-switch endpoint point a user at a
        self-hosted inference URL (lmstudio, ollama, a custom
        OpenAI-compatible gateway) without shipping that literal in
        the adapter's defaults. Unknown provider ids without an
        explicit ``base_url`` no longer silently alias to OpenAI —
        W1 A3 removed that fallback because it was a recurring
        footgun (see the ``unknown`` branch below).

        NOTE: the ``base_url`` kwarg itself was added after W1 in
        response to the shipped v2026.5.0 crash
        (``api/routes/config.py::update_config`` was already passing
        ``base_url=`` but ``switch_provider`` did not accept it ->
        TypeError -> every Save-&-switch 500'd). The regression test
        lives in ``tests/test_switch_provider_base_url.py``.
        """
        client = getattr(self, "client", None)
        if client is not None:
            await client.aclose()

        # Reset the permanent-auth short-circuit. Whatever was wrong
        # before, the user just supplied fresh credentials -- start
        # trying again immediately. Same on switching providers.
        self._auth_permanent_until = {}
        self._auth_permanent_logged = set()

        self.provider = provider
        if model:
            self.model = model

        # Honor the explicit override before the lookup. An empty
        # string is treated as "no override" so legacy callers that
        # always omitted the kwarg keep the auto-resolved default.
        _base_url_override = base_url or ""

        if provider == "lmstudio":
            self.base_url = _base_url_override or "http://localhost:1234/v1"
            self.api_key = "lm-studio"
            if not model:
                detected = self._detect_lmstudio()
                self.model = detected or _default_model_for("lmstudio")
        elif provider == "ollama":
            self.base_url = _base_url_override or ollama_openai_base_url()
            self.api_key = "ollama"
            if not model:
                detected = self._detect_ollama()
                self.model = detected or _default_model_for("ollama")
        elif provider == "local":
            self._init_local_engine()
            if self._local_engine:
                self.available = True
                logger.info(f"Switched to local inference: {self._local_engine.model_id}")
                return
            else:
                logger.warning("Local engine unavailable")
                self.available = False
                return
        elif provider in _PROVIDER_REGISTRY:
            # Runtime-registered provider. Resolve the default base URL
            # + credential env var from the single registry source so
            # openrouter / deepseek / kimi / qwen stay reachable
            # (before W1 A3 these were missing from the local
            # PROVIDER_BASES dict and silently fell through to OpenAI).
            base, env_key = _PROVIDER_REGISTRY[provider]
            self.base_url = _base_url_override or base
            if provider == "gemini":
                self.api_key = api_key or _gemini_api_key() or ""
            elif env_key:
                self.api_key = api_key or os.getenv(env_key, "")
            else:
                self.api_key = api_key
            if not model:
                self.model = _default_model_for(provider)
        else:
            # Unknown / unsupported provider id. Previously we
            # silently defaulted to ``https://api.openai.com/v1`` and
            # reused whatever ``api_key`` the caller passed — which
            # meant a catalog-only descriptor (``bedrock``,
            # ``together``, ``fireworks``) or a typo would send a
            # valid OpenAI-shaped request against OpenAI's endpoint
            # while the UI believed it was on the selected provider.
            # The new contract:
            #   * if the caller supplied ``base_url``, trust it as an
            #     operator-controlled custom OpenAI-compatible gateway
            #     (keeps Save-&-switch working for on-prem setups);
            #   * otherwise refuse the swap — mark the adapter
            #     unavailable and keep the unknown id visible so the
            #     REST / UI layer can report it truthfully.
            logger.warning(
                "switch_provider(%r): provider is not in the runtime "
                "registry. Supported: %s. %s",
                provider,
                sorted(SUPPORTED_RUNTIME_PROVIDERS),
                "Honouring explicit base_url override."
                if _base_url_override
                else "No base_url override supplied — leaving adapter "
                     "unavailable.",
            )
            if _base_url_override:
                self.base_url = _base_url_override
                self.api_key = api_key
                if not model:
                    self.model = _default_model_for(provider)
            else:
                self.base_url = ""
                self.api_key = ""
                if not model:
                    self.model = _default_model_for(provider)
                self.client = self._build_client()
                self.available = False
                logger.info(
                    "Switched LLM to %s/%s (available=False, reason=unsupported_provider)",
                    provider, self.model,
                )
                return

        self.client = self._build_client()
        # Availability requires BOTH a working base_url and a usable
        # credential. Previously ``bool(self.api_key)`` alone said
        # True even when base_url was empty — masking the failure
        # until the next chat call 404'd.
        self.available = bool(self.api_key) and bool(self.base_url)
        logger.info(f"Switched LLM to {provider}/{self.model} (available={self.available})")

    async def reconfigure(
        self,
        *,
        provider: str,
        model: str = "",
        api_key: str = "",
        base_url: str = "",
    ) -> dict:
        """Hot-swap provider / model / key / base_url in one call.

        Same wire as ``switch_provider`` but:
          * accepts ``base_url`` so local providers (LM Studio, custom
            Ollama port) can land end-to-end from the Settings form;
          * returns a structured result the REST layer can surface to
            the UI (``{provider, model, available, reason}``);
          * emits a supervisor event so the swap lands in the audit
            log right alongside user commands.
        """
        if base_url:
            os.environ["FERAL_LLM_BASE_URL"] = base_url
        previous_provider = self.provider
        try:
            await self.switch_provider(provider=provider, model=model, api_key=api_key)
        except Exception as exc:
            logger.warning("reconfigure(%s) failed: %s", provider, exc)
            return {
                "ok": False,
                "provider": provider,
                "model": model,
                "available": False,
                "reason": str(exc),
            }

        reason = "ok" if self.available else "no_api_key"
        try:
            from api.state import state as _state
            sup = getattr(_state, "supervisor", None)
            if sup is not None:
                sup.record(
                    source="config",
                    kind="llm_reconfigure",
                    actor="user",
                    payload={
                        "from": previous_provider,
                        "to": self.provider,
                        "model": self.model,
                        "has_key": bool(self.api_key),
                    },
                    decision="allowed" if self.available else "queued",
                    detail={"reason": reason, "base_url": self.base_url},
                )
        except Exception as exc:
            logger.debug("supervisor.record(llm_reconfigure) failed: %s", exc)

        return {
            "ok": True,
            "provider": self.provider,
            "model": self.model,
            "available": bool(self.available),
            "base_url": self.base_url,
            "reason": reason,
        }

    async def apply_preset(self, preset_id: str) -> dict:
        preset = LLM_PRESETS.get(preset_id)
        if not preset:
            return {"ok": False, "error": f"Unknown preset: {preset_id}"}
        await self.switch_provider(
            provider=preset["provider"],
            model=preset.get("model", ""),
            api_key="",
        )
        return {
            "ok": True,
            "preset": preset_id,
            "provider": self.provider,
            "model": self.model,
            "vision_supported": bool(preset.get("vision_supported", False)),
        }

    # ── Failover ───────────────────────────────────────────

    def set_config(self, config: dict):
        """Accept external config (e.g. from ConfigLoader) for fallback routing."""
        self._config = config

    @staticmethod
    def _float_or_default(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _budget_snapshot(self) -> dict[str, Any]:
        raw_cfg = getattr(self, "_config", {})
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        raw_budget = os.environ.get(
            "FERAL_LLM_DAILY_BUDGET_USD",
            cfg.get("daily_budget_usd", 0.0),
        )
        raw_spend = os.environ.get(
            "FERAL_LLM_DAILY_SPEND_USD",
            cfg.get("daily_spend_usd", 0.0),
        )
        budget = max(0.0, self._float_or_default(raw_budget, 0.0))
        spend = max(0.0, self._float_or_default(raw_spend, 0.0))
        tight_ratio = self._float_or_default(
            os.environ.get(
                "FERAL_LLM_BUDGET_TIGHT_RATIO",
                cfg.get("budget_tight_ratio", 0.25),
            ),
            0.25,
        )
        tight_ratio = min(1.0, max(0.0, tight_ratio))
        remaining = budget - spend
        headroom_ratio = (remaining / budget) if budget > 0 else 1.0
        return {
            "enabled": bool(budget > 0.0),
            "daily_budget_usd": budget,
            "daily_spend_usd": spend,
            "remaining_usd": remaining,
            "headroom_ratio": headroom_ratio,
            "tight_ratio": tight_ratio,
        }

    @staticmethod
    def _message_char_count(messages: list[dict]) -> int:
        total = 0
        for msg in messages or []:
            content = msg.get("content") if isinstance(msg, dict) else ""
            if isinstance(content, str):
                total += len(content)
                continue
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total += len(str(part.get("text", "") or ""))
                    else:
                        total += len(str(part))
        return total

    def _estimate_tokens_for_budget(
        self,
        messages: list[dict],
        kwargs: dict[str, Any],
    ) -> tuple[int, int]:
        prompt_chars = self._message_char_count(messages)
        # Coarse estimate used for candidate ordering only.
        prompt_tokens = max(1, int(prompt_chars / 4) + 1)
        max_tokens = int(kwargs.get("max_tokens", 1024) or 1024)
        completion_tokens = max(1, min(max_tokens, 4096))
        return prompt_tokens, completion_tokens

    def _pricing_for_model(self, provider_name: str, model: str) -> dict[str, float]:
        if not model:
            return {"input": 0.0, "output": 0.0}
        pid = _CATALOG_PROVIDER_MAP.get(provider_name, provider_name)
        try:
            from providers.catalog import get_shared_catalog
            adapter = get_shared_catalog().get_adapter(pid)
        except Exception:
            adapter = None
        if adapter is None:
            return {"input": 0.0, "output": 0.0}
        try:
            pricing = adapter.pricing_per_1k(model) or {}
        except Exception:
            pricing = {}
        input_cost = max(0.0, self._float_or_default(pricing.get("input", 0.0), 0.0))
        output_cost = max(0.0, self._float_or_default(pricing.get("output", 0.0), 0.0))
        return {"input": input_cost, "output": output_cost}

    def _estimate_candidate_cost_usd(
        self,
        provider_name: str,
        config: dict,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        model = str(config.get("model", "") or "")
        if not model and provider_name == self.provider:
            model = str(self.model or "")
        pricing = self._pricing_for_model(provider_name, model)
        if pricing["input"] <= 0.0 and pricing["output"] <= 0.0:
            return 0.0
        in_cost = (float(prompt_tokens) / 1000.0) * pricing["input"]
        out_cost = (float(completion_tokens) / 1000.0) * pricing["output"]
        return max(0.0, in_cost + out_cost)

    def _route_candidates_with_budget(
        self,
        candidates: list[tuple[str, dict]],
        messages: list[dict],
        kwargs: dict[str, Any],
    ) -> tuple[list[tuple[str, dict]], dict[str, Any]]:
        snapshot = self._budget_snapshot()
        if not snapshot["enabled"]:
            return candidates, snapshot

        prompt_tokens, completion_tokens = self._estimate_tokens_for_budget(messages, kwargs)
        remaining = float(snapshot.get("remaining_usd", 0.0))
        annotated: list[dict[str, Any]] = []
        for idx, (provider_name, config) in enumerate(candidates):
            estimated = self._estimate_candidate_cost_usd(
                provider_name,
                config,
                prompt_tokens,
                completion_tokens,
            )
            affordable = estimated <= 0.0 or remaining >= estimated
            annotated.append({
                "idx": idx,
                "provider": provider_name,
                "config": config,
                "estimated_usd": estimated,
                "affordable": affordable,
            })

        affordable = [row for row in annotated if row["affordable"]]
        over_budget = [row for row in annotated if not row["affordable"]]

        headroom_ratio = float(snapshot.get("headroom_ratio", 1.0))
        tight_ratio = float(snapshot.get("tight_ratio", 0.25))
        if affordable and headroom_ratio <= tight_ratio:
            # When budget headroom is low, prefer the cheapest affordable
            # provider first (ties preserve initial candidate order).
            affordable.sort(key=lambda row: (row["estimated_usd"], row["idx"]))
            ordered = affordable + over_budget
        elif affordable:
            # Normal mode: preserve configured provider priority, but defer
            # over-budget candidates to the back of the queue.
            ordered = affordable + over_budget
        else:
            # If every candidate is over budget, keep the system available
            # by trying the cheapest option first instead of hard failing.
            ordered = sorted(over_budget, key=lambda row: (row["estimated_usd"], row["idx"]))

        routed = [(row["provider"], row["config"]) for row in ordered]
        snapshot["prompt_tokens_estimate"] = prompt_tokens
        snapshot["completion_tokens_estimate"] = completion_tokens
        snapshot["candidate_costs"] = [
            {
                "provider": row["provider"],
                "estimated_usd": row["estimated_usd"],
                "affordable": row["affordable"],
            }
            for row in ordered
        ]
        snapshot["over_budget_providers"] = [row["provider"] for row in over_budget]
        return routed, snapshot

    def set_catalog(self, catalog) -> None:
        """Attach the shared :class:`ProviderCatalog` for metadata lookups.

        Commit 1 only stores the reference; the runtime keeps reading
        its primary config from env vars exactly as before so this is
        backward-compatible. Commit 3 flips the primary source over to
        the catalog once every adapter has been reviewed.
        """
        self._catalog = catalog

    @staticmethod
    def _normalize_anthropic_response(data: dict) -> dict:
        """Convert raw Anthropic Messages API response to OpenAI-shaped dict."""
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })
        msg: dict = {"role": "assistant", "content": "\n".join(text_parts)}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return {"choices": [{"message": msg, "finish_reason": data.get("stop_reason", "end_turn")}]}

    def _get_provider_config(self, provider_name: str) -> dict:
        """Resolve base_url / api_key / model for a named provider.

        The model is always resolved through the shared catalog so the
        failover candidate list never contains a stale literal.

        For provider ids that have no runtime binding in this module,
        returns a shape-compatible dict with ``supported=False`` and
        empty URL / key / model. Callers (``_build_candidate_list``,
        ``health_snapshot``, ``is_available``, ``_call_provider``)
        must treat these as unreachable instead of silently
        substituting OpenAI defaults — that substitution was the
        exact footgun this method used to hide behind its two-arg
        ``dict.get`` fallback.
        """
        if provider_name == "ollama":
            return {
                "base_url": ollama_openai_base_url(),
                "api_key": "ollama",
                "model": _default_model_for("ollama") or self._detect_ollama() or "",
                "supported": True,
            }
        if provider_name == "lmstudio":
            detected = self._detect_lmstudio()
            return {
                "base_url": "http://localhost:1234/v1",
                "api_key": "lm-studio",
                "model": detected or _default_model_for("lmstudio"),
                "supported": True,
            }
        reg = _PROVIDER_REGISTRY.get(provider_name)
        if reg is None:
            # Unknown provider id — return an explicitly unsupported
            # config so downstream code can report it honestly
            # instead of silently hitting api.openai.com.
            return {
                "base_url": "",
                "api_key": "",
                "model": _default_model_for(provider_name),
                "supported": False,
            }
        base_url, env_key = reg
        if provider_name == "gemini":
            api_key = _gemini_api_key() or ""
        else:
            api_key = os.getenv(env_key, "") if env_key else ""
        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": _default_model_for(provider_name),
            "supported": True,
        }

    def _build_candidate_list(self) -> list[tuple[str, dict]]:
        """Ordered list of (provider_name, config) — primary first, then fallbacks.

        Every config dict carries a ``supported`` bool so the failover
        loop, health snapshot and availability check can tell runtime
        candidates apart from catalog-only descriptors whose runtime
        adapter hasn't shipped yet.
        """
        candidates: list[tuple[str, dict]] = [
            (self.provider, {
                "base_url": self.base_url,
                "api_key": self.api_key,
                "model": self.model,
                "supported": is_supported_runtime_provider(self.provider),
            }),
        ]
        for fb in self._config.get("fallback_providers", []):
            if fb != self.provider:
                candidates.append((fb, self._get_provider_config(fb)))
        return candidates

    @staticmethod
    def _build_anthropic_body(
        model: str, messages: list[dict], tools: Optional[list[dict]],
        temperature: float, max_tokens: int,
    ) -> dict:
        """Build Anthropic Messages API request body."""
        system_text, conv = _convert_messages_for_anthropic(messages)
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conv,
        }
        if system_text.strip():
            body["system"] = system_text.strip()
        if tools:
            anthropic_tools = []
            for t in tools:
                if t.get("type") == "function":
                    fn = t["function"]
                    anthropic_tools.append({
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
            if anthropic_tools:
                body["tools"] = anthropic_tools
        apply_reasoning_fork("anthropic", model, body)
        _enforce_anthropic_thinking_max_tokens(body)
        return body

    async def _call_provider(
        self,
        provider_name: str,
        config: dict,
        messages: list[dict],
        tools: Optional[list[dict]],
        **kwargs,
    ) -> dict:
        """Make a chat request to a specific provider. Raises on error.

        ``_retry_max`` / ``_retry_delays`` (popped from ``kwargs``) let
        the failover orchestrator dial down same-provider retries when
        a healthy fallback is configured — avoids spending the full
        ``RETRY_DELAYS`` budget on a known-bad provider before routing.
        Defaults preserve historical behaviour for direct callers.
        """
        retry_max = kwargs.pop("_retry_max", None)
        retry_delays = kwargs.pop("_retry_delays", None)
        # Refuse up front for provider ids that have no runtime
        # adapter. Previously the fallback path built an httpx client
        # against whatever default ``_get_provider_config`` handed
        # back — which was OpenAI for any unknown id. That silently
        # turned a user-selected ``bedrock`` fallback into an OpenAI
        # call. Raise a clear error so the failover loop records a
        # cooldown against the right provider name.
        if config.get("supported") is False or not is_supported_runtime_provider(provider_name):
            raise RuntimeError(
                f"Provider {provider_name!r} has no runtime adapter — "
                f"supported: {sorted(SUPPORTED_RUNTIME_PROVIDERS)}"
            )
        selected_model = self.model if provider_name == self.provider else str(config.get("model", "") or "")
        model_guard_error = _chat_completions_model_guard(provider_name, selected_model)
        if model_guard_error:
            raise RuntimeError(model_guard_error)
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 1024)

        # Primary provider — reuse existing client
        if provider_name == self.provider:
            if provider_name == "anthropic":
                body = self._build_anthropic_body(
                    self.model, messages, tools, temperature, max_tokens,
                )

                async def _do_primary_anthropic():
                    resp = await self.client.post("/messages", json=body)
                    resp.raise_for_status()
                    return resp.json()

                data = await _retry_llm_call(
                    _do_primary_anthropic,
                    max_retries=retry_max,
                    delays=retry_delays,
                )
                return self._normalize_anthropic_response(data)

            body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                clean_tools = [{k: v for k, v in t.items() if k != "_feral_meta"} for t in tools]
                if self.provider in ("openai",) and len(clean_tools) > 128:
                    # Same 128-tool cap as the other chat/completions paths.
                    logger.warning(
                        "openai chat/completions (failover primary): truncating "
                        "tools from %d → 128 (OpenAI hard limit).",
                        len(clean_tools),
                    )
                    clean_tools = clean_tools[:128]
                body["tools"] = clean_tools
                body["tool_choice"] = "auto"

            apply_reasoning_fork(self.provider, self.model, body)

            async def _do_primary():
                resp = await self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()

            return await _retry_llm_call(
                _do_primary,
                max_retries=retry_max,
                delays=retry_delays,
            )

        # Fallback provider — build a temporary client
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        if not api_key:
            raise RuntimeError(f"No API key configured for fallback provider '{provider_name}'")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if provider_name == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60.0) as tmp:
            if provider_name == "anthropic":
                body = self._build_anthropic_body(
                    model, messages, tools, temperature, max_tokens,
                )

                async def _do_fb_anthropic():
                    resp = await tmp.post("/messages", json=body)
                    resp.raise_for_status()
                    return resp.json()

                data = await _retry_llm_call(
                    _do_fb_anthropic,
                    max_retries=retry_max,
                    delays=retry_delays,
                )
                return self._normalize_anthropic_response(data)

            body = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                clean_tools = [{k: v for k, v in t.items() if k != "_feral_meta"} for t in tools]
                if provider_name in ("openai",) and len(clean_tools) > 128:
                    # Same 128-tool cap, fallback provider path.
                    logger.warning(
                        "openai chat/completions (failover fallback): truncating "
                        "tools from %d → 128 (OpenAI hard limit).",
                        len(clean_tools),
                    )
                    clean_tools = clean_tools[:128]
                body["tools"] = clean_tools
                body["tool_choice"] = "auto"

            apply_reasoning_fork(provider_name, model, body)

            async def _do_fb():
                resp = await tmp.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()

            return await _retry_llm_call(
                _do_fb,
                max_retries=retry_max,
                delays=retry_delays,
            )

    async def chat_with_failover(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> dict:
        """Call chat() with automatic failover across configured providers.

        Same-provider transient retries are handled by ``_retry_llm_call``.
        Cross-provider routing is handled here based on error classification.
        """
        if self._messages_contain_vision(messages):
            ok, reason = self._vision_support_status()
            if not ok:
                logger.warning(reason)
                return {"error": reason, "choices": []}

        if self._local_engine and self.provider in ("local", "hybrid"):
            return await self.chat(messages, tools, **kwargs)

        from observability.metrics import increment, measure

        candidates = self._build_candidate_list()
        candidates, budget_ctx = self._route_candidates_with_budget(
            candidates,
            messages,
            kwargs,
        )
        self._last_budget_routing = budget_ctx
        last_error: Optional[Exception] = None

        # When at least one supported fallback exists beyond the
        # primary, use the fast-fail retry profile so a transient 5xx
        # on the primary doesn't burn the whole RETRY_DELAYS budget
        # before we even try the fallback. With a single candidate
        # there's nowhere else to go, so keep the historical
        # 3 × [1, 2, 4]s policy.
        viable = [
            name for name, cfg in candidates
            if cfg.get("supported", True)
        ]
        use_fast_retry = len(viable) > 1
        retry_kwargs: dict[str, Any] = {}
        if use_fast_retry:
            retry_kwargs["_retry_max"] = _FAILOVER_FAST_MAX_RETRIES
            retry_kwargs["_retry_delays"] = _FAILOVER_FAST_DELAYS

        for provider_name, config in candidates:
            if not config.get("supported", True):
                # Skip catalog-only providers with no runtime adapter.
                # No cooldown — the problem isn't transient, it's that
                # this module has no wire for them. Logged once per
                # attempt so the ops log shows *why* the candidate was
                # passed over rather than silently dropping it.
                logger.info(
                    "Skipping unsupported provider %r in failover chain",
                    provider_name,
                )
                last_error = last_error or RuntimeError(
                    f"Provider {provider_name!r} has no runtime adapter"
                )
                continue
            if not self._cooldown.should_probe(provider_name):
                continue
            increment("feral.llm.calls_total", attributes={"provider": provider_name, "model": config.get("model", self.model)})
            try:
                with measure("feral.llm.latency", {"provider": provider_name, "model": config.get("model", self.model)}):
                    result = await self._call_provider(
                        provider_name, config, messages, tools,
                        **retry_kwargs, **kwargs,
                    )
                self._cooldown.record_success(provider_name)
                return result
            except Exception as e:
                increment("feral.llm.errors_total", attributes={"provider": provider_name})
                reason = classify_error(e)
                # Honour upstream Retry-After hint when present so the
                # cooldown reflects the provider's actual recovery
                # window instead of our static 60s default.
                retry_after = parse_retry_after(e)
                self._cooldown.record_failure(
                    provider_name, reason, retry_after=retry_after,
                )
                # A5: surface the upstream HTTP body (status + JSON
                # ``error.message`` / ``type`` / ``code`` / ``param``)
                # instead of opaque ``str(e)`` which for
                # ``httpx.HTTPStatusError`` is just the status line. The
                # structured ``extra`` fields make the full body
                # searchable in the ops log / metrics backend; the
                # primary log line stays human-readable.
                detail = _describe_error(e)
                http_status: Any = ""
                error_type = ""
                error_code = ""
                error_param = ""
                body_snippet = ""
                if isinstance(e, httpx.HTTPStatusError):
                    http_status = getattr(e.response, "status_code", "")
                    try:
                        payload = e.response.json()
                    except Exception:
                        payload = {}
                    if isinstance(payload, dict):
                        err_obj = payload.get("error", payload)
                        if isinstance(err_obj, dict):
                            error_type = str(err_obj.get("type", "") or "")
                            error_code = str(err_obj.get("code", "") or "")
                            error_param = str(err_obj.get("param", "") or "")
                    try:
                        body_snippet = (e.response.text or "")[:2048]
                    except Exception:
                        body_snippet = ""
                logger.warning(
                    "Provider %s failed (%s): %s",
                    provider_name, reason.value, detail,
                    extra={
                        "provider": provider_name,
                        "failover_reason": reason.value,
                        "http_status": http_status,
                        "error_type": error_type,
                        "error_code": error_code,
                        "error_param": error_param,
                        "body_snippet": body_snippet,
                    },
                )
                last_error = e
                if reason == FailoverReason.CONTEXT_OVERFLOW:
                    raise
                continue

        if last_error:
            raise last_error
        raise RuntimeError("All LLM providers exhausted")

    def health_snapshot(self) -> dict:
        """Return a snapshot of every candidate provider's availability.

        Used by `GET /api/llm/health` to power the v2 "Fallbacks" card —
        the user can see which providers are live, which are in cooldown,
        and why, without having to dig through server logs.
        """
        now = time.time()
        primary_supported = is_supported_runtime_provider(self.provider)
        primary = {
            "provider": self.provider,
            "model": self.model,
            "has_key": bool(self.api_key) and self.api_key not in ("none", ""),
            "available": bool(self.available) and primary_supported,
            "base_url": self.base_url,
            "supported": primary_supported,
        }
        candidates = []
        try:
            candidate_list = self._build_candidate_list()
        except Exception:
            candidate_list = [(self.provider, {
                "base_url": self.base_url,
                "api_key": self.api_key,
                "model": self.model,
                "supported": primary_supported,
            })]
        for name, cfg in candidate_list:
            until = self._cooldown._cooldowns.get(name, 0.0)
            in_cooldown = until > now
            supported = bool(cfg.get("supported", is_supported_runtime_provider(name)))
            has_key = bool(cfg.get("api_key")) and cfg.get("api_key") not in ("none", "")
            candidates.append({
                "provider": name,
                "model": cfg.get("model") or "",
                "base_url": cfg.get("base_url") or "",
                "has_key": has_key,
                "in_cooldown": in_cooldown,
                "cooldown_until": until if in_cooldown else None,
                "cooldown_remaining": max(0.0, until - now) if in_cooldown else 0.0,
                "supported": supported,
            })
        fallbacks = list(self._config.get("fallback_providers", [])) if isinstance(self._config, dict) else []
        budget = self._budget_snapshot()
        last_budget = getattr(self, "_last_budget_routing", {})
        if isinstance(last_budget, dict) and last_budget:
            budget["last_routing"] = {
                "remaining_usd": last_budget.get("remaining_usd"),
                "candidate_costs": last_budget.get("candidate_costs", []),
                "over_budget_providers": last_budget.get("over_budget_providers", []),
                "prompt_tokens_estimate": last_budget.get("prompt_tokens_estimate", 0),
                "completion_tokens_estimate": last_budget.get("completion_tokens_estimate", 0),
            }
        return {
            "active": primary,
            "candidates": candidates,
            "fallback_providers": fallbacks,
            "budget": budget,
            # Total ready-to-serve = supported AND has key AND not in cooldown.
            # Unsupported candidates were counted as "available" before W1 A3
            # whenever a lookalike env var happened to be set, inflating the
            # fallbacks card with providers the runtime could never actually
            # call.
            "total_available": sum(
                1 for c in candidates
                if c["has_key"] and not c["in_cooldown"] and c["supported"]
            ),
        }

    def is_available(self) -> bool:
        """True if at least one provider has a valid key and is not in cooldown.

        A primary or fallback that has no runtime adapter
        (``is_supported_runtime_provider`` False) never counts — even
        if the corresponding credential env var happens to be set.
        """
        if not self.available:
            return False
        if self._local_engine and self.provider in ("local", "hybrid"):
            return True
        if self.provider in ("ollama", "lmstudio"):
            return True
        if (
            is_supported_runtime_provider(self.provider)
            and self.api_key and self.api_key not in ("none", "")
            and self.base_url
            and self._cooldown.is_available(self.provider)
        ):
            return True
        for fb in self._config.get("fallback_providers", []):
            if fb == self.provider:
                continue
            cfg = self._get_provider_config(fb)
            if not cfg.get("supported"):
                continue
            if cfg.get("api_key") and self._cooldown.is_available(fb):
                return True
        return False

    async def close(self):
        client = getattr(self, "client", None)
        if client is not None:
            await client.aclose()
