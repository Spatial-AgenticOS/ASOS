"""
FERAL LLM Provider — Pluggable AI Backend
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

from config.runtime import ollama_base_url, ollama_openai_base_url

logger = logging.getLogger("feral.llm")

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
            resp = await self.client.post("/messages", json=body)
            resp.raise_for_status()
            data = resp.json()

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

        try:
            async with self.client.stream("POST", "/chat/completions", json=body) as resp:
                resp.raise_for_status()

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

    async def close(self):
        client = getattr(self, "client", None)
        if client is not None:
            await client.aclose()
