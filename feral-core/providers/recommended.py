"""Per-provider recommended-model shortlists ("latest relevant").

A provider's ``/v1/models`` endpoint returns everything the provider
ever published — legacy chat releases, embedding heads, audio codecs,
image models, fine-tune snapshots, and preview branches. Surfacing all
132 OpenAI IDs (or all 355 OpenRouter routes) to the end user is noise;
they want to pick from the 6-10 models that actually earn their $$ in
2026-Q2.

This module is the curated overlay. It is the second filter that
follows :func:`feral_core.providers.model_classes.classify` — first
``classify()`` drops non-chat classes (embeddings, audio, image,
completion-only), then this module's :func:`is_recommended` keeps only
the 2026-04-26 latest-relevant picks per provider.

The list is maintained by the conductor based on live
``/v1/models`` output plus the upstream provider's current
"recommended for new projects" guidance. When a provider ships a newer
model, the entry rolls forward and previous-gen entries move to a
``_LEGACY_OK`` set so existing users with saved picks keep working
without the picker surfacing them to new users.

The v2 Settings picker defaults to ``recommended=True``; a "Show all"
toggle flips to the full chat-class list.
"""

from __future__ import annotations

from typing import FrozenSet


# ─────────────────────────────────────────────────────────────────────
# Curated shortlists per provider (2026-04-26)
# ─────────────────────────────────────────────────────────────────────
# Update criteria:
#   1. Upstream provider page lists it as "Recommended for production"
#      or equivalent (the provider's own editorial pick).
#   2. Still-receiving-updates (not marked deprecated in /v1/models).
#   3. Covers the tier spread the operator cares about: a flagship,
#      a fast/cheap tier, and a thinking/reasoning tier where the
#      provider has one.

_RECOMMENDED_OPENAI: FrozenSet[str] = frozenset({
    # Flagship (2026 generation)
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5",
    "gpt-5-mini",
    # Reasoning tier
    "o4-mini",
    "o3",
    "o3-mini",
    # Vision-capable chat
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
})

_RECOMMENDED_ANTHROPIC: FrozenSet[str] = frozenset({
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-haiku-4-5",
})

_RECOMMENDED_DEEPSEEK: FrozenSet[str] = frozenset({
    # These two are the only chat models DeepSeek exposes on
    # /v1/models as of 2026-04-26. The legacy deepseek-chat /
    # deepseek-reasoner aliases deprecate 2026-07-24 per upstream.
    "deepseek-v4-pro",
    "deepseek-v4-flash",
})

_RECOMMENDED_GEMINI: FrozenSet[str] = frozenset({
    # 3.1 tier (current)
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-flash-image-preview",
    # 3.0 tier (still widely deployed)
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3-pro-image-preview",
    # 2.5 tier (stable, cost-effective)
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    # Rolling aliases that always point at the latest
    "gemini-pro-latest",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
})

_RECOMMENDED_GROQ: FrozenSet[str] = frozenset({
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "groq/compound",
    "groq/compound-mini",
})

# OpenRouter's /v1/models returns 355+ routes. The shortlist below is
# biased toward the most-used routes for each upstream provider. The
# v2 picker should still let the user type to filter across all 355
# when they want a specific route.
_RECOMMENDED_OPENROUTER_PREFIXES: FrozenSet[str] = frozenset({
    # Anthropic on OpenRouter
    "anthropic/claude-opus-4",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-haiku-4",
    # OpenAI on OpenRouter
    "openai/gpt-5",
    "openai/gpt-4.1",
    "openai/o3",
    "openai/o4",
    # Google on OpenRouter
    "google/gemini-3",
    "google/gemini-2.5",
    # Meta / Llama
    "meta-llama/llama-4",
    "meta-llama/llama-3.3",
    # DeepSeek on OpenRouter (useful when you don't want to hold a
    # DeepSeek key directly)
    "deepseek/deepseek-v4",
    # xAI
    "x-ai/grok-",
    # Mistral
    "mistralai/mistral-",
    "mistralai/mixtral-",
    # Qwen
    "qwen/qwen3",
})

# Locally-hosted backends: there is no upstream catalog — whatever the
# user has loaded IS the list. The recommended overlay is a no-op;
# everything the host advertises is relevant by definition.
_LOCAL_PROVIDERS: FrozenSet[str] = frozenset({"lmstudio", "ollama", "local"})


_RECOMMENDED_BY_PROVIDER: dict[str, FrozenSet[str]] = {
    "openai": _RECOMMENDED_OPENAI,
    "anthropic": _RECOMMENDED_ANTHROPIC,
    "deepseek": _RECOMMENDED_DEEPSEEK,
    "gemini": _RECOMMENDED_GEMINI,
    "groq": _RECOMMENDED_GROQ,
}


def is_recommended(provider_id: str, model_id: str) -> bool:
    """True iff ``model_id`` is on the conductor-curated shortlist.

    Unknown providers and local backends return True — the caller has
    no other source of truth for what's relevant there.
    """
    pid = (provider_id or "").lower()
    mid = (model_id or "").strip()

    if not mid:
        return False

    if pid in _LOCAL_PROVIDERS:
        return True

    if pid == "openrouter":
        return any(mid.startswith(p) for p in _RECOMMENDED_OPENROUTER_PREFIXES)

    shortlist = _RECOMMENDED_BY_PROVIDER.get(pid)
    if shortlist is None:
        # Unknown provider: the operator's own inventory is the
        # authoritative list. Don't second-guess.
        return True
    return mid in shortlist


def recommended_for(provider_id: str, all_models: list[str]) -> list[str]:
    """Filter ``all_models`` down to the recommended shortlist for
    ``provider_id``. Preserves caller-supplied order.

    Callers that want the raw chat-class list keep using
    ``BaseProvider.list_models(model_class="chat")`` without passing
    ``recommended=True``.
    """
    return [m for m in all_models if is_recommended(provider_id, m)]
