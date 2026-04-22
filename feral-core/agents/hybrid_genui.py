"""HybridGenerator — render a GenUI app surface by combining authored
templates, publisher defaults, and LLM fallback.

Sits in front of the existing ``GenUIEngine`` so v2 third-party apps
get the hybrid behaviour the plan specifies:

1. ``kind=authored`` → fill the publisher's authored ``template_root``
   with ``$data.*`` bindings, no LLM.
2. ``kind=generated`` → if a per-user cache exists, hydrate it with the
   current data binding; else prefer a pre-rendered publisher default
   if present in the bundle; else call the LLM, cache the result.
3. ``kind=hybrid`` → authored template is the default; the agent
   regenerates a personalised version only when an explicit
   customization signal fires (``regenerate=True``).

This module lives alongside ``app_registry.py`` because the registry
owns install lifecycle while the generator owns render lifecycle.
Re-exports are provided so existing callers can still import from
``agents.app_registry`` without churn.
"""

from __future__ import annotations

from agents.app_registry import (  # noqa: F401
    HybridGenerator,
    default_hybrid_cache_dir,
)
