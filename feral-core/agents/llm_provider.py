"""
FERAL LLM Provider — Pluggable AI Backend
=====================================================
Supports: OpenAI API, Ollama (local), and any OpenAI-compatible endpoint.
Now with streaming support for real-time token delivery.
"""

from __future__ import annotations
import asyncio
import os
import json
import logging
import time
import httpx
from enum import Enum
from typing import Optional, AsyncGenerator

from config.runtime import ollama_base_url, ollama_openai_base_url

logger = logging.getLogger("feral.llm")

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # seconds
_RETRIABLE_CODES = ("429", "500", "502", "503", "504", "timeout", "connection")


async def _retry_llm_call(coro_factory):
    """Retry an LLM HTTP call with exponential backoff on transient errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return await coro_factory()
        except Exception as e:
            err_str = str(e).lower()
            retriable = any(code in err_str for code in _RETRIABLE_CODES)
            if not retriable or attempt == MAX_RETRIES - 1:
                raise
            logger.warning("LLM call failed (attempt %d/%d): %s — retrying in %ds",
                           attempt + 1, MAX_RETRIES, e, RETRY_DELAYS[attempt])
            await asyncio.sleep(RETRY_DELAYS[attempt])

VISION_READY_OLLAMA_MODELS = (
    "llava",
    "moondream",
    "qwen2-vl",
    "minicpm-v",
    "bakllava",
    "gemma3",
)

LLM_PRESETS = {
    "ollama_text": {
        "provider": "ollama",
        "model": "llama3.1",
        "description": "Local text path on Ollama",
        "vision_supported": False,
    },
    "ollama_vision": {
        "provider": "ollama",
        "model": "llava",
        "description": "Local vision path on Ollama VLM",
        "vision_supported": True,
    },
    "openai_default": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "description": "Cloud default for balanced latency/quality",
        "vision_supported": True,
    },
}


# ── Failover Error Classification ─────────────────────────────


class FailoverReason(str, Enum):
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    AUTH_PERMANENT = "auth_permanent"
    BILLING = "billing"
    MODEL_NOT_FOUND = "model_not_found"
    CONTEXT_OVERFLOW = "context_overflow"
    TIMEOUT = "timeout"
    OVERLOADED = "overloaded"
    UNKNOWN = "unknown"


def classify_error(error: Exception) -> FailoverReason:
    """Classify an LLM error into a failover reason for routing decisions."""
    err_str = str(error).lower()
    status = getattr(error, "status_code", 0) or 0
    if hasattr(error, "response"):
        status = getattr(error.response, "status_code", status) or status

    if status == 429 or "rate" in err_str or "quota" in err_str:
        return FailoverReason.RATE_LIMIT
    if status == 401 or "unauthorized" in err_str or "invalid api key" in err_str:
        return FailoverReason.AUTH
    if "billing" in err_str or "payment" in err_str or "insufficient" in err_str:
        return FailoverReason.BILLING
    if status == 404 or ("model" in err_str and "not found" in err_str):
        return FailoverReason.MODEL_NOT_FOUND
    if "context" in err_str and ("length" in err_str or "overflow" in err_str or "too long" in err_str):
        return FailoverReason.CONTEXT_OVERFLOW
    if "timeout" in err_str or status == 408 or "timed out" in err_str:
        return FailoverReason.TIMEOUT
    if status in (500, 502, 503) or "overloaded" in err_str or "server error" in err_str:
        return FailoverReason.OVERLOADED
    return FailoverReason.UNKNOWN


class ProviderCooldownTracker:
    """Tracks per-provider cooldown state for failover decisions."""

    _COOLDOWN_MAP: dict[FailoverReason, int] = {
        FailoverReason.RATE_LIMIT: 60,
        FailoverReason.AUTH: 300,
        FailoverReason.AUTH_PERMANENT: 86400,
        FailoverReason.BILLING: 3600,
        FailoverReason.OVERLOADED: 30,
        FailoverReason.TIMEOUT: 15,
    }
    _PROBE_INTERVAL = 30.0

    def __init__(self):
        self._cooldowns: dict[str, float] = {}
        self._last_probe: dict[str, float] = {}

    def record_failure(self, provider: str, reason: FailoverReason):
        cooldown_seconds = self._COOLDOWN_MAP.get(reason, 10)
        self._cooldowns[provider] = time.time() + cooldown_seconds

    def is_available(self, provider: str) -> bool:
        return time.time() >= self._cooldowns.get(provider, 0)

    def should_probe(self, provider: str) -> bool:
        if self.is_available(provider):
            return True
        last = self._last_probe.get(provider, 0)
        if time.time() - last >= self._PROBE_INTERVAL:
            self._last_probe[provider] = time.time()
            return True
        return False

    def record_success(self, provider: str):
        self._cooldowns.pop(provider, None)


_PROVIDER_REGISTRY: dict[str, tuple[str, str, str]] = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.1-70b-versatile"),
    "anthropic": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "claude-sonnet-4-20250514"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openai/gpt-4.1"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-chat"),
    "kimi": ("https://api.moonshot.cn/v1", "MOONSHOT_API_KEY", "moonshot-v1-128k"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY", "qwen-max"),
}


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
        self.provider = os.getenv("FERAL_LLM_PROVIDER", "openai")
        self.model = os.getenv("FERAL_LLM_MODEL", "gpt-4o-mini")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("FERAL_LLM_BASE_URL", "")
        self.available = True
        self._config: dict = {}
        self._cooldown = ProviderCooldownTracker()

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
            self.base_url = self.base_url or ollama_openai_base_url()
            self.model = self.model or "llama3"
            self.api_key = "ollama"
        elif self.provider == "groq":
            self.base_url = self.base_url or "https://api.groq.com/openai/v1"
            self.api_key = os.getenv("GROQ_API_KEY", self.api_key)
        elif self.provider == "anthropic":
            self.base_url = self.base_url or "https://api.anthropic.com/v1"
            self.api_key = os.getenv("ANTHROPIC_API_KEY", self.api_key)
            self.model = self.model or "claude-sonnet-4-20250514"
        elif self.provider == "gemini":
            self.base_url = self.base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
            self.api_key = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", self.api_key))
            self.model = self.model or "gemini-2.5-flash"
        elif self.provider == "openrouter":
            self.base_url = self.base_url or "https://openrouter.ai/api/v1"
            self.api_key = os.getenv("OPENROUTER_API_KEY", self.api_key)
            self.model = self.model or "openai/gpt-4.1"
        elif self.provider == "deepseek":
            self.base_url = self.base_url or "https://api.deepseek.com"
            self.api_key = os.getenv("DEEPSEEK_API_KEY", self.api_key)
            self.model = self.model or "deepseek-chat"
        elif self.provider == "kimi":
            self.base_url = self.base_url or "https://api.moonshot.cn/v1"
            self.api_key = os.getenv("MOONSHOT_API_KEY", self.api_key)
            self.model = self.model or "moonshot-v1-128k"
        elif self.provider == "qwen":
            self.base_url = self.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            self.api_key = os.getenv("DASHSCOPE_API_KEY", self.api_key)
            self.model = self.model or "qwen-max"
        else:
            self.base_url = self.base_url or "https://api.openai.com/v1"

        # Check if API key is available — if not, try Ollama fallback
        if not self.api_key and self.provider != "ollama":
            logger.warning(f"No API key for provider '{self.provider}'. Trying Ollama fallback...")
            ollama_model = self._detect_ollama()
            if ollama_model:
                self.provider = "ollama"
                self.base_url = ollama_openai_base_url()
                self.model = ollama_model
                self.api_key = "ollama"
                logger.info(f"Ollama detected — using model '{ollama_model}'")
            else:
                logger.warning(
                    "No LLM available. Set OPENAI_API_KEY or run Ollama (`ollama serve`). "
                    "Brain will operate in direct-execution mode (no reasoning, skill matching only)."
                )
                self.available = False
                self.api_key = "none"

        self.client = self._build_client()

        status = "READY" if self.available else "DIRECT-EXECUTION MODE (no LLM)"
        logger.info(f"LLM Provider: {self.provider} | Model: {self.model} | Status: {status}")

    @staticmethod
    def list_presets() -> list[dict]:
        return [{"id": k, **v} for k, v in LLM_PRESETS.items()]

    def _build_client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.provider == "anthropic":
            headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=60.0)

    @staticmethod
    def _detect_ollama() -> Optional[str]:
        """Probe Ollama for running models. Returns best model name or None."""
        preferred = ["llama3.1", "llama3", "mistral", "gemma2", "phi3", "qwen2"]
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"{ollama_base_url().rstrip('/')}/api/tags", timeout=3)
            data = json.loads(resp.read())
            models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
            if not models:
                logger.info("Ollama running but no models pulled. Try: ollama pull llama3.1")
                return None
            for pref in preferred:
                if pref in models:
                    return pref
            return models[0]
        except Exception:
            return None

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
        if self._messages_contain_vision(messages):
            ok, reason = self._vision_support_status()
            if not ok:
                logger.warning(reason)
                return {"error": reason, "choices": []}

        # Local inference path
        if self._local_engine and self.provider in ("local", "hybrid"):
            use_local = self.provider == "local" or not self._hybrid_cloud_provider
            if self.provider == "hybrid" and tools:
                use_local = False

            if use_local:
                return await self._chat_local(messages, tools, temperature, max_tokens)

        if self.provider == "anthropic":
            return await self._chat_anthropic(messages, tools, temperature, max_tokens)

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            clean_tools = []
            for tool in tools:
                clean = {k: v for k, v in tool.items() if k != "_feral_meta"}
                clean_tools.append(clean)
            body["tools"] = clean_tools
            body["tool_choice"] = "auto"

        try:
            async def _do_chat():
                resp = await self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()

            return await _retry_llm_call(_do_chat)
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

    @staticmethod
    def _messages_contain_vision(messages: list[dict]) -> bool:
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_type = str(block.get("type", ""))
                        if block_type in ("image_url", "input_image", "image", "image_base64"):
                            return True
                        if "image_url" in block:
                            return True
            elif isinstance(content, dict):
                block_type = str(content.get("type", ""))
                if block_type in ("image_url", "input_image", "image", "image_base64"):
                    return True
                if "image_url" in content:
                    return True
        return False

    def _vision_support_status(self) -> tuple[bool, str]:
        if self.provider in ("openai", "gemini"):
            return True, ""

        if self.provider == "ollama":
            model_lower = (self.model or "").lower()
            if any(hint in model_lower for hint in VISION_READY_OLLAMA_MODELS):
                return True, ""
            return (
                False,
                "Current Ollama model does not appear vision-capable. "
                "Use a VLM model such as 'llava' or apply preset 'ollama_vision'.",
            )

        if self.provider in ("local", "hybrid") and self._local_engine:
            if getattr(self._local_engine, "supports_vision", False):
                return True, ""
            return (
                False,
                "Local inference engine is text-only and cannot process images. "
                "Use Ollama VLM for local vision (`provider=ollama`, model `llava`).",
            )

        return False, f"Provider '{self.provider}' does not support vision input."

    async def _chat_anthropic(
        self, messages: list[dict], tools: Optional[list[dict]],
        temperature: float, max_tokens: int,
    ) -> dict:
        """Anthropic Messages API → normalized to OpenAI format."""
        system_text = ""
        conv_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text += m.get("content", "") + "\n"
            else:
                conv_messages.append({"role": m["role"], "content": m.get("content", "")})

        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conv_messages,
        }
        if system_text.strip():
            body["system"] = system_text.strip()

        if tools:
            anthropic_tools = []
            for t in tools:
                if t.get("type") == "function":
                    fn = t["function"]
                    anthropic_tools.append({
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
            if anthropic_tools:
                body["tools"] = anthropic_tools

        try:
            async def _do_anthropic():
                resp = await self.client.post("/messages", json=body)
                resp.raise_for_status()
                return resp.json()

            data = await _retry_llm_call(_do_anthropic)

            text_parts = []
            tool_calls = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })

            msg: dict = {"role": "assistant", "content": "\n".join(text_parts)}
            if tool_calls:
                msg["tool_calls"] = tool_calls

            return {"choices": [{"message": msg, "finish_reason": data.get("stop_reason", "end_turn")}]}
        except httpx.HTTPStatusError as e:
            logger.error(f"Anthropic API error: {e.response.status_code} — {e.response.text[:500]}")
            return {"error": str(e), "choices": []}
        except Exception as e:
            logger.error(f"Anthropic call failed: {e}")
            return {"error": str(e), "choices": []}

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
        if self._messages_contain_vision(messages):
            ok, reason = self._vision_support_status()
            if not ok:
                yield {"type": "error", "content": reason}
                return

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

        # Anthropic native streaming (Messages API with SSE)
        if self.provider == "anthropic":
            async for delta in self._chat_stream_anthropic(messages, tools, temperature, max_tokens):
                yield delta
            return

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            clean_tools = [{k: v for k, v in t.items() if k != "_feral_meta"} for t in tools]
            body["tools"] = clean_tools
            body["tool_choice"] = "auto"

        stream_cm = None
        try:
            for _attempt in range(MAX_RETRIES):
                try:
                    stream_cm = self.client.stream("POST", "/chat/completions", json=body)
                    resp = await stream_cm.__aenter__()
                    resp.raise_for_status()
                    break
                except Exception as e:
                    if stream_cm:
                        try:
                            await stream_cm.__aexit__(type(e), e, e.__traceback__)
                        except Exception:
                            pass
                        stream_cm = None
                    err_str = str(e).lower()
                    retriable = any(c in err_str for c in _RETRIABLE_CODES)
                    if not retriable or _attempt == MAX_RETRIES - 1:
                        raise
                    logger.warning("LLM stream connect failed (attempt %d/%d) — retrying",
                                   _attempt + 1, MAX_RETRIES)
                    await asyncio.sleep(RETRY_DELAYS[_attempt])

            accumulated_tool_calls: dict[int, dict] = {}
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
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

                if delta.get("content"):
                    yield {"type": "text_delta", "content": delta["content"]}

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
        finally:
            if stream_cm:
                try:
                    await stream_cm.__aexit__(None, None, None)
                except Exception:
                    pass

    async def _chat_stream_anthropic(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[dict, None]:
        """Native Anthropic Messages API streaming via SSE."""
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        system_prompt = ""
        anthropic_messages = []
        for m in messages:
            if m["role"] == "system":
                system_prompt = m["content"] if isinstance(m["content"], str) else str(m["content"])
            else:
                anthropic_messages.append({"role": m["role"], "content": m["content"]})

        body: dict = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            body["system"] = system_prompt
        if tools:
            body["tools"] = [
                {
                    "name": t.get("function", {}).get("name", t.get("name", "")),
                    "description": t.get("function", {}).get("description", ""),
                    "input_schema": t.get("function", {}).get("parameters", {}),
                }
                for t in tools if t.get("type") == "function" or "function" in t
            ]

        accumulated_tool_calls: dict[str, dict] = {}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=body,
                ) as resp:
                    resp.raise_for_status()
                    current_tool_id = ""
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if not data_str:
                            continue
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        if event_type == "content_block_start":
                            block = event.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool_id = block.get("id", "")
                                accumulated_tool_calls[current_tool_id] = {
                                    "id": current_tool_id,
                                    "name": block.get("name", ""),
                                    "arguments": "",
                                }

                        elif event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield {"type": "text_delta", "content": delta.get("text", "")}
                            elif delta.get("type") == "input_json_delta":
                                if current_tool_id in accumulated_tool_calls:
                                    accumulated_tool_calls[current_tool_id]["arguments"] += delta.get("partial_json", "")

                        elif event_type == "message_delta":
                            pass

                        elif event_type == "message_stop":
                            for tc in accumulated_tool_calls.values():
                                try:
                                    tc["args"] = json.loads(tc.get("arguments", "{}"))
                                except json.JSONDecodeError:
                                    tc["args"] = {}
                                yield {"type": "tool_call_delta", "tool_call": tc}
                            yield {"type": "done"}
                            return

            yield {"type": "done"}
        except httpx.HTTPStatusError as e:
            logger.error(f"Anthropic stream error: {e.response.status_code}")
            yield {"type": "error", "content": str(e)}
        except Exception as e:
            logger.error(f"Anthropic stream failed: {e}")
            yield {"type": "error", "content": str(e)}

    async def switch_provider(self, provider: str, model: str = "", api_key: str = ""):
        """Hot-swap the LLM provider at runtime."""
        client = getattr(self, "client", None)
        if client is not None:
            await client.aclose()

        self.provider = provider
        if model:
            self.model = model

        PROVIDER_DEFAULTS = {
            "ollama": (ollama_openai_base_url(), "OLLAMA_DUMMY", "llama3.1"),
            "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.1-70b-versatile"),
            "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
            "anthropic": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "claude-sonnet-4-20250514"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.0-flash"),
        }

        if provider == "ollama":
            self.base_url = ollama_openai_base_url()
            self.api_key = "ollama"
            if not model:
                detected = self._detect_ollama()
                self.model = detected or "llama3.1"
        elif provider == "local":
            self._init_local_engine()
            if self._local_engine:
                self.available = True
                logger.info(f"Switched to local inference: {self._local_engine.model_id}")
                return
            else:
                logger.warning("Local engine unavailable")
                self.available = False
                return
        elif provider in PROVIDER_DEFAULTS:
            base, env_key, default_model = PROVIDER_DEFAULTS[provider]
            self.base_url = base
            self.api_key = api_key or os.getenv(env_key, "")
            if not model:
                self.model = default_model
        else:
            self.base_url = os.getenv("FERAL_LLM_BASE_URL", "https://api.openai.com/v1")
            self.api_key = api_key

        self.client = self._build_client()
        self.available = bool(self.api_key)
        logger.info(f"Switched LLM to {provider}/{self.model} (available={self.available})")

    async def apply_preset(self, preset_id: str) -> dict:
        preset = LLM_PRESETS.get(preset_id)
        if not preset:
            return {"ok": False, "error": f"Unknown preset: {preset_id}"}
        await self.switch_provider(
            provider=preset["provider"],
            model=preset.get("model", ""),
            api_key="",
        )
        return {
            "ok": True,
            "preset": preset_id,
            "provider": self.provider,
            "model": self.model,
            "vision_supported": bool(preset.get("vision_supported", False)),
        }

    # ── Failover ───────────────────────────────────────────

    def set_config(self, config: dict):
        """Accept external config (e.g. from ConfigLoader) for fallback routing."""
        self._config = config

    @staticmethod
    def _normalize_anthropic_response(data: dict) -> dict:
        """Convert raw Anthropic Messages API response to OpenAI-shaped dict."""
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })
        msg: dict = {"role": "assistant", "content": "\n".join(text_parts)}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return {"choices": [{"message": msg, "finish_reason": data.get("stop_reason", "end_turn")}]}

    def _get_provider_config(self, provider_name: str) -> dict:
        """Resolve base_url / api_key / model for a named provider."""
        if provider_name == "ollama":
            return {
                "base_url": ollama_openai_base_url(),
                "api_key": "ollama",
                "model": "llama3.1",
            }
        reg = _PROVIDER_REGISTRY.get(
            provider_name,
            ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
        )
        base_url, env_key, default_model = reg
        api_key = os.getenv(env_key, "")
        if provider_name == "gemini" and not api_key:
            api_key = os.getenv("GOOGLE_API_KEY", "")
        return {"base_url": base_url, "api_key": api_key, "model": default_model}

    def _build_candidate_list(self) -> list[tuple[str, dict]]:
        """Ordered list of (provider_name, config) — primary first, then fallbacks."""
        candidates: list[tuple[str, dict]] = [
            (self.provider, {"base_url": self.base_url, "api_key": self.api_key, "model": self.model}),
        ]
        for fb in self._config.get("fallback_providers", []):
            if fb != self.provider:
                candidates.append((fb, self._get_provider_config(fb)))
        return candidates

    @staticmethod
    def _build_anthropic_body(
        model: str, messages: list[dict], tools: Optional[list[dict]],
        temperature: float, max_tokens: int,
    ) -> dict:
        """Build Anthropic Messages API request body."""
        system_text = ""
        conv: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                system_text += m.get("content", "") + "\n"
            else:
                conv.append({"role": m["role"], "content": m.get("content", "")})
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conv,
        }
        if system_text.strip():
            body["system"] = system_text.strip()
        if tools:
            anthropic_tools = []
            for t in tools:
                if t.get("type") == "function":
                    fn = t["function"]
                    anthropic_tools.append({
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
            if anthropic_tools:
                body["tools"] = anthropic_tools
        return body

    async def _call_provider(
        self,
        provider_name: str,
        config: dict,
        messages: list[dict],
        tools: Optional[list[dict]],
        **kwargs,
    ) -> dict:
        """Make a chat request to a specific provider. Raises on error."""
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 1024)

        # Primary provider — reuse existing client
        if provider_name == self.provider:
            if provider_name == "anthropic":
                body = self._build_anthropic_body(
                    self.model, messages, tools, temperature, max_tokens,
                )

                async def _do_primary_anthropic():
                    resp = await self.client.post("/messages", json=body)
                    resp.raise_for_status()
                    return resp.json()

                data = await _retry_llm_call(_do_primary_anthropic)
                return self._normalize_anthropic_response(data)

            body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                body["tools"] = [{k: v for k, v in t.items() if k != "_feral_meta"} for t in tools]
                body["tool_choice"] = "auto"

            async def _do_primary():
                resp = await self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()

            return await _retry_llm_call(_do_primary)

        # Fallback provider — build a temporary client
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        if not api_key:
            raise RuntimeError(f"No API key configured for fallback provider '{provider_name}'")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if provider_name == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60.0) as tmp:
            if provider_name == "anthropic":
                body = self._build_anthropic_body(
                    model, messages, tools, temperature, max_tokens,
                )

                async def _do_fb_anthropic():
                    resp = await tmp.post("/messages", json=body)
                    resp.raise_for_status()
                    return resp.json()

                data = await _retry_llm_call(_do_fb_anthropic)
                return self._normalize_anthropic_response(data)

            body = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                body["tools"] = [{k: v for k, v in t.items() if k != "_feral_meta"} for t in tools]
                body["tool_choice"] = "auto"

            async def _do_fb():
                resp = await tmp.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()

            return await _retry_llm_call(_do_fb)

    async def chat_with_failover(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> dict:
        """Call chat() with automatic failover across configured providers.

        Same-provider transient retries are handled by ``_retry_llm_call``.
        Cross-provider routing is handled here based on error classification.
        """
        if self._messages_contain_vision(messages):
            ok, reason = self._vision_support_status()
            if not ok:
                logger.warning(reason)
                return {"error": reason, "choices": []}

        if self._local_engine and self.provider in ("local", "hybrid"):
            return await self.chat(messages, tools, **kwargs)

        candidates = self._build_candidate_list()
        last_error: Optional[Exception] = None

        for provider_name, config in candidates:
            if not self._cooldown.should_probe(provider_name):
                continue
            try:
                result = await self._call_provider(provider_name, config, messages, tools, **kwargs)
                self._cooldown.record_success(provider_name)
                return result
            except Exception as e:
                reason = classify_error(e)
                self._cooldown.record_failure(provider_name, reason)
                logger.warning("Provider %s failed (%s): %s", provider_name, reason.value, e)
                last_error = e
                if reason == FailoverReason.CONTEXT_OVERFLOW:
                    raise
                continue

        if last_error:
            raise last_error
        raise RuntimeError("All LLM providers exhausted")

    async def close(self):
        client = getattr(self, "client", None)
        if client is not None:
            await client.aclose()
