"""
THEORA LLM Provider — Pluggable AI Backend (v0.4.0)
=====================================================
Supports: OpenAI API, Ollama (local), and any OpenAI-compatible endpoint.
Now with streaming support for real-time token delivery.
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
    - Local on-device inference (MLX on Apple Silicon, llama.cpp elsewhere)
    - Hybrid mode (local for routing, cloud for reasoning)
    """

    def __init__(self):
        self.provider = os.getenv("THEORA_LLM_PROVIDER", "openai")
        self.model = os.getenv("THEORA_LLM_MODEL", "gpt-4o-mini")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("THEORA_LLM_BASE_URL", "")
        self.available = True

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
        """
        # Local inference path
        if self._local_engine and self.provider in ("local", "hybrid"):
            use_local = self.provider == "local" or not self._hybrid_cloud_provider
            if self.provider == "hybrid" and tools:
                use_local = False

            if use_local:
                return await self._chat_local(messages, tools, temperature, max_tokens)

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

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            clean_tools = [{k: v for k, v in t.items() if k != "_theora_meta"} for t in tools]
            body["tools"] = clean_tools
            body["tool_choice"] = "auto"

        try:
            async with self.client.stream("POST", "/chat/completions", json=body) as resp:
                resp.raise_for_status()

                accumulated_tool_calls: dict[int, dict] = {}
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        # Emit accumulated tool calls
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

                    # Text content
                    if delta.get("content"):
                        yield {"type": "text_delta", "content": delta["content"]}

                    # Tool calls (streamed in fragments)
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
            logger.error(f"LLM stream error: {e.response.status_code}")
            yield {"type": "error", "content": str(e)}
        except Exception as e:
            logger.error(f"LLM stream failed: {e}")
            yield {"type": "error", "content": str(e)}

    async def close(self):
        await self.client.aclose()
