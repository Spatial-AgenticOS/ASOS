"""Ollama provider adapter — talks to a local Ollama server."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("feral.providers.ollama")


class OllamaProvider(BaseProvider):
    provider_id = "ollama"
    display_name = "Ollama (local)"

    _models = ["llama3.3", "qwen2.5", "deepseek-r1", "mistral"]
    _pricing = {m: {"input": 0.0, "output": 0.0} for m in _models}
    _capabilities = {"streaming", "tool_calling"}

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._base_url = (base_url or "http://localhost:11434").rstrip("/")

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
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
        }
        if max_tokens is not None or temperature is not None:
            options: dict[str, Any] = {}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            if temperature is not None:
                options["temperature"] = temperature
            payload["options"] = options
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(f"{self._base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        msg = data.get("message", {})
        return ChatResponse(
            text=msg.get("content", ""),
            model=data.get("model", model),
            usage={
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            },
            finish_reason="stop",
            tool_calls=msg.get("tool_calls", []),
        )

    async def refresh_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self._base_url}/api/tags")
            r.raise_for_status()
        ids = [m["name"] for m in r.json().get("models", [])]
        if ids:
            self._models = sorted(ids)
        return list(self._models)
