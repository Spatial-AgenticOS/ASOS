"""
THEORA LLM Provider — Pluggable AI Backend
============================================
Supports: OpenAI API, Ollama (local), and any OpenAI-compatible endpoint.
The brain doesn't care which model is running. Swap with one env var.
"""

from __future__ import annotations
import os
import json
import logging
import httpx
from typing import Optional, AsyncGenerator

logger = logging.getLogger("theora.llm")


class LLMProvider:
    """
    Pluggable LLM interface.
    
    Supports:
    - OpenAI API (GPT-4o, GPT-4o-mini)
    - Ollama local (llama3, mistral, etc.)
    - Any OpenAI-compatible endpoint (Groq, Together, etc.)
    """

    def __init__(self):
        self.provider = os.getenv("THEORA_LLM_PROVIDER", "openai")
        self.model = os.getenv("THEORA_LLM_MODEL", "gpt-4o-mini")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("THEORA_LLM_BASE_URL", "")
        self.available = True

        # Set defaults based on provider
        if self.provider == "ollama":
            self.base_url = self.base_url or "http://localhost:11434/v1"
            self.model = self.model or "llama3"
            self.api_key = "ollama"
        elif self.provider == "groq":
            self.base_url = "https://api.groq.com/openai/v1"
            self.api_key = os.getenv("GROQ_API_KEY", self.api_key)
        else:
            self.base_url = self.base_url or "https://api.openai.com/v1"

        # Check if API key is available — if not, try Ollama fallback
        if not self.api_key and self.provider != "ollama":
            logger.warning(f"No API key for provider '{self.provider}'. Trying Ollama fallback...")
            try:
                # Quick sync check if Ollama is running
                import urllib.request
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
                self.provider = "ollama"
                self.base_url = "http://localhost:11434/v1"
                self.model = "llama3"
                self.api_key = "ollama"
                logger.info("Ollama detected — using local model as fallback")
            except Exception:
                logger.warning(
                    "No LLM available. Set OPENAI_API_KEY or run Ollama. "
                    "Brain will operate in direct-execution mode (no reasoning, skill matching only)."
                )
                self.available = False
                self.api_key = "none"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )

        status = "READY" if self.available else "DIRECT-EXECUTION MODE (no LLM)"
        logger.info(f"LLM Provider: {self.provider} | Model: {self.model} | Status: {status}")

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
        """
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            # Strip our internal _theora_meta from tool definitions
            clean_tools = []
            for tool in tools:
                clean = {k: v for k, v in tool.items() if k != "_theora_meta"}
                clean_tools.append(clean)
            body["tools"] = clean_tools
            body["tool_choice"] = "auto"

        try:
            resp = await self.client.post("/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API error: {e.response.status_code} — {e.response.text[:500]}")
            return {"error": str(e), "choices": []}
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return {"error": str(e), "choices": []}

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

    async def close(self):
        await self.client.aclose()
