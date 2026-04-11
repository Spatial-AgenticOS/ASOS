"""
FERAL Local LLM Inference — MLX + llama.cpp
==============================================
Embedded inference that runs in-process — no external server.

- MLXEngine: Apple Silicon Macs via mlx-lm (Metal-accelerated)
- LlamaCppEngine: Cross-platform CPU/CUDA via llama-cpp-python

Model management in ~/.feral/models/ with auto-download from HuggingFace.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import platform
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, AsyncGenerator

from config.loader import feral_data_home

logger = logging.getLogger("feral.local_inference")

MODELS_DIR = feral_data_home() / "models"


class LocalLLMEngine(ABC):
    """Abstract interface for local inference engines."""

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.loaded = False
        self.supports_vision = False

    @abstractmethod
    async def load_model(self):
        ...

    @abstractmethod
    async def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        ...

    @abstractmethod
    async def generate_stream(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> AsyncGenerator[str, None]:
        ...

    @abstractmethod
    async def unload(self):
        ...

    def format_chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> str:
        """Convert chat messages to a plain prompt for local models."""
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            normalized, has_vision = self._normalize_content(content)
            if has_vision and not self.supports_vision:
                raise ValueError(
                    "Local model received image content but this local engine is text-only. "
                    "Use Ollama VLM via FERAL_VLM_PROVIDER=ollama (for scene/vision) or "
                    "switch to a provider/model that supports multimodal input."
                )
            if role == "system":
                parts.append(f"<|system|>\n{normalized}")
            elif role == "user":
                parts.append(f"<|user|>\n{normalized}")
            elif role == "assistant":
                parts.append(f"<|assistant|>\n{normalized}")
            elif role == "tool":
                parts.append(f"<|tool|>\n{normalized}")

        if tools:
            tool_desc = json.dumps([{"name": t.get("function", {}).get("name", ""), "description": t.get("function", {}).get("description", "")} for t in tools[:10]], indent=2)
            parts.insert(1, f"<|tools|>\n{tool_desc}")

        parts.append("<|assistant|>\n")
        return "\n".join(parts)

    @staticmethod
    def _normalize_content(content: object) -> tuple[str, bool]:
        if isinstance(content, str):
            return content, False

        if isinstance(content, list):
            text_parts: list[str] = []
            has_vision = False
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                    continue
                if not isinstance(block, dict):
                    text_parts.append(str(block))
                    continue

                block_type = str(block.get("type", ""))
                if block_type in ("text", "input_text"):
                    text_parts.append(str(block.get("text", "")))
                elif block_type in ("image_url", "input_image", "image", "image_base64"):
                    has_vision = True
                elif "text" in block:
                    text_parts.append(str(block.get("text", "")))
                else:
                    text_parts.append(json.dumps(block))
            return "\n".join(p for p in text_parts if p).strip(), has_vision

        if isinstance(content, dict):
            if content.get("type") in ("image_url", "input_image", "image", "image_base64"):
                return "", True
            if "text" in content:
                return str(content.get("text", "")), False
            return json.dumps(content), False

        return str(content), False

    def parse_tool_calls(self, text: str) -> tuple[str, list[dict]]:
        """Try to extract tool calls from model output."""
        tool_calls = []
        clean_text = text

        import re
        pattern = r'\{["\']?name["\']?\s*:\s*["\'](\w+)["\'].*?["\']?args["\']?\s*:\s*(\{.*?\})\s*\}'
        matches = re.finditer(pattern, text, re.DOTALL)
        for match in matches:
            try:
                name = match.group(1)
                args = json.loads(match.group(2))
                tool_calls.append({"id": f"local_{int(time.time())}", "name": name, "args": args})
                clean_text = text[:match.start()] + text[match.end():]
            except (json.JSONDecodeError, IndexError):
                continue

        return clean_text.strip(), tool_calls


class MLXEngine(LocalLLMEngine):
    """Apple Silicon inference via mlx-lm."""

    def __init__(self, model_id: str):
        super().__init__(model_id)
        self._model = None
        self._tokenizer = None

    async def load_model(self):
        def _load():
            try:
                from mlx_lm import load as mlx_load
                model, tokenizer = mlx_load(self.model_id)
                return model, tokenizer
            except ImportError:
                raise RuntimeError("mlx-lm not installed. Run: pip install mlx-lm")
            except Exception as e:
                raise RuntimeError(f"Failed to load MLX model {self.model_id}: {e}")

        loop = asyncio.get_event_loop()
        self._model, self._tokenizer = await loop.run_in_executor(None, _load)
        self.loaded = True
        logger.info(f"MLX model loaded: {self.model_id}")

    async def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        if not self.loaded:
            await self.load_model()

        def _generate():
            from mlx_lm import generate as mlx_generate
            return mlx_generate(
                self._model, self._tokenizer, prompt=prompt,
                max_tokens=max_tokens, temp=temperature,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _generate)

    async def generate_stream(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> AsyncGenerator[str, None]:
        if not self.loaded:
            await self.load_model()

        def _stream():
            try:
                from mlx_lm import stream_generate
                return list(stream_generate(
                    self._model, self._tokenizer, prompt=prompt,
                    max_tokens=max_tokens, temp=temperature,
                ))
            except ImportError:
                from mlx_lm import generate as mlx_generate
                result = mlx_generate(
                    self._model, self._tokenizer, prompt=prompt,
                    max_tokens=max_tokens, temp=temperature,
                )
                return [result]

        loop = asyncio.get_event_loop()
        tokens = await loop.run_in_executor(None, _stream)
        for token in tokens:
            yield token if isinstance(token, str) else str(token)

    async def unload(self):
        self._model = None
        self._tokenizer = None
        self.loaded = False
        logger.info(f"MLX model unloaded: {self.model_id}")


class LlamaCppEngine(LocalLLMEngine):
    """Cross-platform inference via llama-cpp-python."""

    def __init__(self, model_id: str):
        super().__init__(model_id)
        self._llm = None
        self._model_path = None

    async def load_model(self):
        def _load():
            try:
                from llama_cpp import Llama
            except ImportError:
                raise RuntimeError("llama-cpp-python not installed. Run: pip install llama-cpp-python")

            model_path = self._resolve_model_path()
            n_gpu = -1 if self._has_gpu() else 0

            return Llama(
                model_path=str(model_path),
                n_ctx=4096,
                n_gpu_layers=n_gpu,
                verbose=False,
            )

        loop = asyncio.get_event_loop()
        self._llm = await loop.run_in_executor(None, _load)
        self.loaded = True
        logger.info(f"llama.cpp model loaded: {self.model_id}")

    def _resolve_model_path(self) -> Path:
        """Find or download the GGUF model."""
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        # Check if model_id is already a path
        direct_path = Path(self.model_id)
        if direct_path.exists():
            return direct_path

        # Check models directory
        for f in MODELS_DIR.rglob("*.gguf"):
            if self.model_id.replace("/", "_") in f.stem:
                return f

        # Try HuggingFace download
        try:
            from huggingface_hub import hf_hub_download
            parts = self.model_id.split(":")
            repo = parts[0] if len(parts) > 0 else self.model_id
            filename = parts[1] if len(parts) > 1 else None

            if not filename:
                from huggingface_hub import list_repo_files
                files = list_repo_files(repo)
                gguf_files = [f for f in files if f.endswith(".gguf")]
                q4_files = [f for f in gguf_files if "q4" in f.lower() or "Q4" in f]
                filename = q4_files[0] if q4_files else (gguf_files[0] if gguf_files else None)

            if filename:
                path = hf_hub_download(repo, filename, local_dir=str(MODELS_DIR))
                return Path(path)
        except Exception as e:
            logger.warning(f"HuggingFace download failed: {e}")

        raise FileNotFoundError(f"Model not found: {self.model_id}. Place a .gguf file in {MODELS_DIR}")

    @staticmethod
    def _has_gpu() -> bool:
        try:
            import subprocess
            subprocess.run(["nvidia-smi"], capture_output=True, check=True)
            return True
        except Exception:
            return platform.system() == "Darwin"

    async def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        if not self.loaded:
            await self.load_model()

        def _generate():
            result = self._llm(prompt, max_tokens=max_tokens, temperature=temperature)
            return result["choices"][0]["text"]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _generate)

    async def generate_stream(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> AsyncGenerator[str, None]:
        if not self.loaded:
            await self.load_model()

        def _stream():
            chunks = []
            for token in self._llm(prompt, max_tokens=max_tokens, temperature=temperature, stream=True):
                text = token["choices"][0]["text"]
                chunks.append(text)
            return chunks

        loop = asyncio.get_event_loop()
        tokens = await loop.run_in_executor(None, _stream)
        for token in tokens:
            yield token

    async def unload(self):
        self._llm = None
        self.loaded = False
        logger.info(f"llama.cpp model unloaded: {self.model_id}")


def create_local_engine(model_spec: str = "") -> LocalLLMEngine:
    """
    Factory: create the right engine based on spec and platform.
    Spec format: "mlx:<model_id>" or "gguf:<model_id>" or just "<model_id>"
    """
    if not model_spec:
        model_spec = os.getenv("FERAL_LOCAL_MODEL", "")

    if model_spec.startswith("mlx:"):
        return MLXEngine(model_spec[4:])
    elif model_spec.startswith("gguf:"):
        return LlamaCppEngine(model_spec[5:])

    # Auto-detect: prefer MLX on Apple Silicon
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        default = model_spec or "mlx-community/Qwen2.5-7B-Instruct-4bit"
        return MLXEngine(default)
    else:
        default = model_spec or "TheBloke/Mistral-7B-Instruct-v0.2-GGUF"
        return LlamaCppEngine(default)
