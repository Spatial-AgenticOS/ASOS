"""Anthropic provider adapter.

Calls the public ``/v1/messages`` API. Anthropic has no ``/v1/models``
endpoint, so ``refresh_models`` falls back to the hand-curated catalog
in ``providers/model_catalog.json``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("feral.providers.anthropic")


class AnthropicProvider(BaseProvider):
    provider_id = "anthropic"
    display_name = "Anthropic"

    # Hand-curated as of 2026-04-24. Anthropic does not expose a public
    # /v1/models endpoint, so this list IS the catalog — bumping it is
    # the only way new Claude IDs reach the v2 picker until provider
    # docs add a discovery endpoint. Mirrors anthropic.models in
    # feral-core/providers/model_catalog.json (curated_at 2026-04-24).
    _models = [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-sonnet-4-5",
    ]
    _pricing = {
        "claude-opus-4-7": {"input": 0.018, "output": 0.09},
        "claude-sonnet-4-6": {"input": 0.0035, "output": 0.018},
        "claude-haiku-4-5": {"input": 0.0008, "output": 0.004},
        "claude-opus-4-6": {"input": 0.015, "output": 0.075},
        "claude-opus-4-5": {"input": 0.015, "output": 0.075},
        "claude-sonnet-4-5": {"input": 0.003, "output": 0.015},
    }
    _capabilities = {"tool_calling", "vision", "streaming", "thinking"}

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self._api_key = api_key
        self._base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: Optional[int] = 4096,
        temperature: Optional[float] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self._api_key:
            raise RuntimeError("anthropic provider has no api_key configured")

        system_chunks: list[str] = []
        turns: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_chunks.append(m.content)
                continue
            turns.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or 4096,
            "messages": turns,
        }
        if system_chunks:
            payload["system"] = "\n\n".join(system_chunks)
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                f"{self._base_url}/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        tool_blocks = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
        usage = data.get("usage", {})
        return ChatResponse(
            text="".join(text_blocks),
            model=data.get("model", model),
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
            finish_reason=data.get("stop_reason", "end_turn"),
            tool_calls=tool_blocks,
        )

    async def refresh_models(self) -> list[str]:
        # Anthropic does not expose /v1/models publicly; the scheduled
        # research script hand-curates the catalog file instead.
        return list(self._models)
