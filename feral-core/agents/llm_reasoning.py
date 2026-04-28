"""Reasoning-family request-body shaping for LLM providers.

Each provider's reasoning models accept a different param contract on
``/v1/chat/completions`` (and the Anthropic Messages API). These helpers
mutate the outbound body in-place so the dispatcher in
``agents.llm_provider`` stays provider-agnostic. Extracted from
``agents.llm_provider`` (W3-A15); re-exported from there for import
compatibility.
"""

from __future__ import annotations


def _apply_openai_reasoning_fork(model: str, body: dict) -> dict:
    """Rewrite *body* for OpenAI's reasoning-family contract.

    gpt-5, gpt-5.4*, gpt-5.5*, o1/o3/o4: Chat Completions rejects
    ``max_tokens`` and non-1 ``temperature`` / ``top_p`` / penalty
    params with a 400 (this is the exact shape of the v2026.5.0 shipped
    400s). The fix: rename to ``max_completion_tokens`` and strip.
    Non-reasoning models (gpt-4o, gpt-4.1) pass through untouched.

    Imported locally to keep module-load order simple — providers.model_classes
    has no side-effects beyond regex compilation.
    """
    from providers.model_classes import classify
    if classify("openai", model) != "reasoning":
        return body
    if "max_tokens" in body and "max_completion_tokens" not in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
    else:
        body.pop("max_tokens", None)
    temp = body.get("temperature")
    if temp is not None and temp != 1 and temp != 1.0:
        body.pop("temperature", None)
    for key in ("top_p", "presence_penalty", "frequency_penalty"):
        body.pop(key, None)
    body.setdefault("reasoning_effort", "medium")
    return body


def _apply_deepseek_reasoning_fork(model: str, body: dict) -> dict:
    """Rewrite *body* for DeepSeek's thinking-mode contract.

    v4-pro / deepseek-reasoner demand ``extra_body.thinking`` enabled
    and reject sampling params in strict mode. v4-flash / deepseek-chat
    are pass-through.
    """
    from providers.model_classes import classify
    if classify("deepseek", model) != "reasoning":
        return body
    extra = body.setdefault("extra_body", {})
    if not isinstance(extra, dict):
        extra = {}
        body["extra_body"] = extra
    extra.setdefault("thinking", {"type": "enabled"})
    body.setdefault("reasoning_effort", "high")
    for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
        body.pop(key, None)
    return body


def _apply_gemini_reasoning_fork(model: str, body: dict) -> dict:
    """Rewrite *body* for Gemini's thinkingConfig contract.

    ``-thinking`` variants accept ``generationConfig.thinkingConfig.enabled=true``.
    Non-thinking Gemini 3.x rejects the block with a 400.
    """
    from providers.model_classes import classify
    if classify("gemini", model) != "reasoning":
        return body
    gen_cfg = body.setdefault("generationConfig", {})
    thinking_cfg = gen_cfg.setdefault("thinkingConfig", {})
    thinking_cfg.setdefault("enabled", True)
    return body


def _apply_anthropic_reasoning_fork(model: str, body: dict) -> dict:
    """Rewrite *body* for Anthropic's thinking contract.

    Extended-thinking models (Sonnet 4.6, Haiku 4.5, Sonnet / Opus 4.5)
    accept ``thinking={"type":"enabled","budget_tokens":N}`` and require
    ``temperature=1``. Adaptive-thinking models (Opus 4.7) decline the
    explicit block — the model chooses its own depth.
    """
    from providers.model_classes import classify
    if classify("anthropic", model) != "reasoning":
        return body
    # Import lazily to avoid circular import at module load.
    from providers.anthropic_provider import (
        AnthropicProvider,
        _default_budget_tokens,
    )
    probe = AnthropicProvider(api_key="_probe_")
    if probe.supports_extended_thinking(model):
        budget = _default_budget_tokens(model)
        if budget:
            body.setdefault("thinking", {
                "type": "enabled",
                "budget_tokens": int(budget),
            })
            body.pop("temperature", None)
    elif probe.supports_adaptive_thinking(model):
        body.pop("thinking", None)
        # Live smoke on 2026-04-26 confirmed: claude-opus-4-7 returns
        # 400 ``temperature is deprecated for this model`` when any
        # temperature value is sent. The adaptive-thinking contract
        # says the model chooses its own behaviour; temperature is no
        # longer a caller-controlled knob for this class. Drop it.
        body.pop("temperature", None)
    return body


def _apply_groq_reasoning_fork(model: str, body: dict) -> dict:
    """Mirror the OpenAI fork for Groq-hosted reasoning models."""
    from providers.model_classes import classify
    if classify("groq", model) != "reasoning":
        return body
    if "max_tokens" in body and "max_completion_tokens" not in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
    temp = body.get("temperature")
    if temp is not None and temp != 1 and temp != 1.0:
        body.pop("temperature", None)
    for key in ("top_p", "presence_penalty", "frequency_penalty"):
        body.pop(key, None)
    body.setdefault("reasoning_effort", "medium")
    return body


def apply_reasoning_fork(provider: str, model: str, body: dict) -> dict:
    """Provider-router wrapper around the per-provider reasoning forks.

    Called at every chat-body assembly site in the dispatcher so the
    outbound wire-shape matches the selected model's reasoning contract.
    Non-reasoning models pass through untouched. ``body`` is mutated
    in-place AND returned for caller convenience. See
    ``docs/mintlify/providers/reasoning-models.mdx`` for the full
    per-provider param table.
    """
    pid = (provider or "").lower()
    if pid == "openai":
        return _apply_openai_reasoning_fork(model, body)
    if pid == "deepseek":
        return _apply_deepseek_reasoning_fork(model, body)
    if pid == "gemini":
        return _apply_gemini_reasoning_fork(model, body)
    if pid == "anthropic":
        return _apply_anthropic_reasoning_fork(model, body)
    if pid == "groq":
        return _apply_groq_reasoning_fork(model, body)
    return body


__all__ = [
    "_apply_openai_reasoning_fork",
    "_apply_deepseek_reasoning_fork",
    "_apply_gemini_reasoning_fork",
    "_apply_anthropic_reasoning_fork",
    "_apply_groq_reasoning_fork",
    "apply_reasoning_fork",
]
