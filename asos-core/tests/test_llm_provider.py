"""
Tests for ``LLMProvider``: env-based setup, Anthropic normalization, streaming, and hot-swap.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agents.llm_provider import LLMProvider


@pytest.fixture
def anthropic_env() -> dict[str, str]:
    return {
        "THEORA_LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "THEORA_LLM_MODEL": "claude-test-model",
    }


class TestLLMProviderInit:
    def test_init_detects_provider_from_env(self, anthropic_env: dict[str, str]) -> None:
        with patch.dict(os.environ, anthropic_env, clear=False):
            with patch.object(LLMProvider, "_detect_ollama", return_value=None):
                llm = LLMProvider()
        assert llm.provider == "anthropic"
        assert "anthropic.com" in llm.base_url or llm.base_url.endswith("/v1")
        assert llm.model == "claude-test-model"

    def test_available_property_true_with_key(self, anthropic_env: dict[str, str]) -> None:
        with patch.dict(os.environ, anthropic_env, clear=False):
            with patch.object(LLMProvider, "_detect_ollama", return_value=None):
                llm = LLMProvider()
        assert llm.available is True

    def test_available_false_without_keys_and_no_ollama(self) -> None:
        env = {
            "THEORA_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(LLMProvider, "_detect_ollama", return_value=None):
                llm = LLMProvider()
        assert llm.available is False


class TestChatAnthropic:
    @pytest.mark.asyncio
    async def test_chat_anthropic_normalizes_openai_shape(self, anthropic_env: dict[str, str]) -> None:
        anthropic_payload = {
            "content": [
                {"type": "text", "text": "Hello from Claude"},
            ],
            "stop_reason": "end_turn",
        }

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = anthropic_payload

        post_mock = AsyncMock(return_value=mock_resp)

        with patch.dict(os.environ, anthropic_env, clear=False):
            with patch.object(LLMProvider, "_detect_ollama", return_value=None):
                llm = LLMProvider()
        llm.client.post = post_mock

        out = await llm._chat_anthropic(
            [{"role": "user", "content": "Hi"}],
            tools=None,
            temperature=0.5,
            max_tokens=128,
        )

        post_mock.assert_awaited_once()
        call_kw = post_mock.call_args
        assert call_kw[0][0] == "/messages"
        body = call_kw[1]["json"]
        assert body["model"] == llm.model
        assert body["messages"] == [{"role": "user", "content": "Hi"}]

        text, tools = llm.extract_response(out)
        assert text == "Hello from Claude"
        assert tools == []


class TestChatStream:
    @pytest.mark.asyncio
    async def test_chat_stream_yields_text_delta_and_done(self) -> None:
        env = {
            "THEORA_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-openai-test",
            "THEORA_LLM_MODEL": "gpt-test",
        }

        lines = [
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "data: [DONE]",
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_stream_resp = MagicMock()
        mock_stream_resp.raise_for_status = MagicMock()
        mock_stream_resp.aiter_lines = aiter_lines

        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=mock_stream_resp)
        stream_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.dict(os.environ, env, clear=False):
            with patch.object(LLMProvider, "_detect_ollama", return_value=None):
                llm = LLMProvider()
        llm.client.stream = MagicMock(return_value=stream_cm)

        events: list[dict] = []
        async for ev in llm.chat_stream([{"role": "user", "content": "x"}], tools=None):
            events.append(ev)

        texts = [e["content"] for e in events if e.get("type") == "text_delta"]
        assert "".join(texts) == "Hello"
        assert events[-1] == {"type": "done"}


class TestSwitchProvider:
    @pytest.mark.asyncio
    async def test_switch_provider_updates_base_url_and_model(self) -> None:
        env = {
            "THEORA_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-x",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(LLMProvider, "_detect_ollama", return_value=None):
                llm = LLMProvider()

        await llm.switch_provider("groq", model="llama-custom", api_key="gq-key")

        assert llm.provider == "groq"
        assert llm.base_url == "https://api.groq.com/openai/v1"
        assert llm.model == "llama-custom"
        assert llm.api_key == "gq-key"

        await llm.close()
