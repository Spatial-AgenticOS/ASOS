"""DeepSeek provider adapter (OpenAI-compatible /v1/chat/completions)."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("feral.providers.deepseek")


class DeepSeekProvider(BaseProvider):
    provider_id = "deepseek"
    display_name = "DeepSeek"

    _models = ["deepseek-chat", "deepseek-reasoner"]
    _pricing = {
        "deepseek-chat": {"input": 0.00027, "output": 0.0011},
        "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
    }
    _capabilities = {"tool_calling", "streaming", "thinking"}

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self._api_key = api_key
        self._base_url = (base_url or "https://api.deepseek.com/v1").rstrip("/")

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
            raise RuntimeError("deepseek provider has no api_key configured")
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
        async with httpx.AsyncClient(timeout=90.0) as c:
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
            text=msg.get("content", ""),
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
            logger.debug("deepseek refresh_models failed: %s", exc)
        return list(self._models)
