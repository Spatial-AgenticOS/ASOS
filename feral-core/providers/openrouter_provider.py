"""OpenRouter provider adapter (OpenAI-compatible /v1/chat/completions).

Track A stub: shape matches production; live-credential tests queued.
OpenRouter aggregates 100+ upstream models, so ``refresh_models`` is the
main win — it keeps the local catalog in sync without a code change.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("feral.providers.openrouter")


class OpenRouterProvider(BaseProvider):
    provider_id = "openrouter"
    display_name = "OpenRouter"

    _models = [
        "anthropic/claude-3.7-sonnet",
        "openai/gpt-4o-mini",
        "meta-llama/llama-3.1-70b-instruct",
        "google/gemini-2.0-flash-exp",
    ]
    _pricing: dict[str, dict[str, float]] = {}
    _capabilities = {"tool_calling", "streaming"}

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        referer: str = "https://feral.ai",
        title: str = "FERAL",
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        # OpenRouter asks integrators to send these for ranking + abuse control.
        self._referer = referer
        self._title = title

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": self._referer,
            "X-Title": self._title,
        }
        return headers

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
            raise RuntimeError("openrouter provider has no api_key configured")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
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
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        choice = data["choices"][0]
        msg = choice["message"]
        return ChatResponse(
            text=msg.get("content", ""),
            model=data.get("model", model),
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", "stop"),
            tool_calls=msg.get("tool_calls") or [],
        )

    async def refresh_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30.0) as c:
            # OpenRouter's /models endpoint is public — keyless refresh
            # works, so the catalog stays up to date even without
            # credentials.
            r = await c.get(f"{self._base_url}/models")
            r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and "id" in m]
        if ids:
            self._models = sorted(ids)
        return list(self._models)
