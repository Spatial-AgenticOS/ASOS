"""Tests for agents.local_inference — OllamaEngine + factory helpers."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agents.local_inference import (
    OllamaEngine,
    create_local_engine,
    LocalLLMEngine,
    MLXEngine,
    LlamaCppEngine,
    auto_setup_vision,
)


# ── OllamaEngine health check ───────────────────────────────────

async def test_health_check_success():
    engine = OllamaEngine(model_id="llama3.2:3b", base_url="http://fake:11434")
    mock_resp = MagicMock(status_code=200)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.local_inference.httpx.AsyncClient", return_value=mock_client):
        assert await engine.health_check() is True


async def test_health_check_failure():
    engine = OllamaEngine(model_id="llama3.2:3b", base_url="http://fake:11434")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.local_inference.httpx.AsyncClient", return_value=mock_client):
        assert await engine.health_check() is False


# ── OllamaEngine chat ───────────────────────────────────────────

async def test_ollama_chat():
    engine = OllamaEngine(model_id="llama3.2:3b", base_url="http://fake:11434")
    engine.loaded = True

    resp = MagicMock()
    resp.json.return_value = {"message": {"content": "Hello!"}}
    resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.local_inference.httpx.AsyncClient", return_value=mock_client):
        result = await engine.chat([{"role": "user", "content": "Hi"}])
    assert result == "Hello!"


# ── OllamaEngine generate ───────────────────────────────────────

async def test_ollama_generate():
    engine = OllamaEngine(model_id="llama3.2:3b", base_url="http://fake:11434")
    engine.loaded = True

    resp = MagicMock()
    resp.json.return_value = {"response": "The answer is 42."}
    resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.local_inference.httpx.AsyncClient", return_value=mock_client):
        result = await engine.generate("What is the meaning?")
    assert result == "The answer is 42."


# ── create_local_engine factory ──────────────────────────────────

def test_create_engine_ollama_prefix():
    engine = create_local_engine("ollama:mistral")
    assert isinstance(engine, OllamaEngine)
    assert engine.model_id == "mistral"


def test_create_engine_mlx_prefix():
    engine = create_local_engine("mlx:some-model")
    assert isinstance(engine, MLXEngine)
    assert engine.model_id == "some-model"


def test_create_engine_gguf_prefix():
    engine = create_local_engine("gguf:some-gguf-model")
    assert isinstance(engine, LlamaCppEngine)
    assert engine.model_id == "some-gguf-model"


# ── auto_setup_vision ────────────────────────────────────────────

async def test_auto_setup_vision_finds_existing():
    tags_resp = MagicMock(status_code=200)
    tags_resp.json.return_value = {"models": [{"name": "llava:7b"}]}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=tags_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.local_inference.httpx.AsyncClient", return_value=mock_client):
        result = await auto_setup_vision("http://fake:11434")
    assert result["available"] is True
    assert result["model"] == "llava:7b"


async def test_auto_setup_vision_ollama_unreachable():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.local_inference.httpx.AsyncClient", return_value=mock_client):
        result = await auto_setup_vision("http://fake:11434")
    assert result["available"] is False


# ── format_chat ──────────────────────────────────────────────────

def test_format_chat_basic():
    engine = OllamaEngine()
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi there"},
    ]
    prompt = engine.format_chat(messages)
    assert "<|system|>" in prompt
    assert "<|user|>" in prompt
    assert prompt.endswith("<|assistant|>\n")


def test_format_chat_with_tools():
    engine = OllamaEngine()
    messages = [{"role": "user", "content": "Search for cats"}]
    tools = [{"function": {"name": "search", "description": "Web search"}}]
    prompt = engine.format_chat(messages, tools=tools)
    assert "<|tools|>" in prompt
    assert "search" in prompt
