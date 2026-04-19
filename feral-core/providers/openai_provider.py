"""OpenAI provider adapter.

Thin wrapper that exposes the existing OpenAI client used elsewhere in
the codebase behind the pluggable :class:`Provider` Protocol. The
real inference code in ``agents/`` and ``voice/`` continues to use the
raw OpenAI SDK; this adapter is for the capability / pricing / model-
listing surface the orchestrator uses to pick models.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("feral.providers.openai")


class OpenAIProvider(BaseProvider):
    provider_id = "openai"
    display_name = "OpenAI"

    # Populated from model_catalog.json on load; seed with commonly
    # available models so a fresh install works before the first
    # catalog refresh.
    _models = [
        "gpt-5",
        "gpt-5-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "o1",
        "o1-mini",
        "text-embedding-3-small",
        "text-embedding-3-large",
    ]
    _pricing = {
        # USD per 1k tokens — source of truth is model_catalog.json; these
        # are backstops.
        "gpt-5": {"input": 0.005, "output": 0.015},
        "gpt-5-mini": {"input": 0.0003, "output": 0.0012},
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    }
    _capabilities = {"tool_calling", "json_mode", "vision", "streaming", "audio_in", "audio_out"}

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self._api_key = api_key
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

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
        if not self._api_key:
            raise RuntimeError("openai provider has no api_key configured")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_msg_to_openai(m) for m in messages],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        choice = data["choices"][0]
        msg = choice["message"]
        return ChatResponse(
            text=msg.get("content") or "",
            model=data.get("model", model),
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", "stop"),
            tool_calls=msg.get("tool_calls") or [],
        )

    async def refresh_models(self) -> list[str]:
        if not self._api_key:
            return list(self._models)
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                r.raise_for_status()
            ids = [m["id"] for m in r.json().get("data", [])]
            if ids:
                self._models = sorted(ids)
        except Exception as exc:
            logger.debug("openai refresh_models failed: %s", exc)
        return list(self._models)


def _msg_to_openai(m: ChatMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.name:
        out["name"] = m.name
    if m.tool_calls:
        out["tool_calls"] = m.tool_calls
    return out
