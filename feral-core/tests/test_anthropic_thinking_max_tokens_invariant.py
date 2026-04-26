"""Regression test for Anthropic's max_tokens > thinking.budget_tokens invariant.

Evidence from a live smoke against Anthropic on 2026-04-26 with
claude-sonnet-4-6 at ``max_tokens=20``:

    400 {"type":"error","error":{"type":"invalid_request_error",
    "message":"`max_tokens` must be greater than `thinking.budget_tokens`"}}

The fix: when the adapter adds ``thinking.budget_tokens=N``, it must
raise ``max_tokens`` to at least ``N + 1024`` to leave room for the
post-thinking response.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.anthropic_provider import AnthropicProvider
from providers.base import ChatMessage


@pytest.fixture
def adapter() -> AnthropicProvider:
    return AnthropicProvider(api_key="test-key-do-not-commit")


def _fake_anthropic_response():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": "live"}],
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    return mock_response


def _capture_payload(adapter: AnthropicProvider, **kwargs) -> dict:
    with patch("providers.anthropic_provider.httpx.AsyncClient") as client_cls:
        instance = client_cls.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=_fake_anthropic_response())
        asyncio.run(adapter.chat(
            messages=[ChatMessage(role="user", content="hi")],
            **kwargs,
        ))
        call = instance.post.await_args
        return call.kwargs["json"]


class TestBumpMaxTokens:
    def test_tiny_max_tokens_is_bumped_for_sonnet_4_6(self, adapter):
        # Caller passed max_tokens=20, thinking.budget_tokens defaults
        # to 16000 for sonnet. max_tokens MUST be bumped so the live
        # API doesn't 400 on the invariant.
        payload = _capture_payload(adapter, model="claude-sonnet-4-6", max_tokens=20)
        assert "thinking" in payload
        budget = payload["thinking"]["budget_tokens"]
        assert payload["max_tokens"] > budget, (
            f"max_tokens={payload['max_tokens']} must be > "
            f"thinking.budget_tokens={budget}; Anthropic rejects with 400 otherwise"
        )
        # At least 1024 tokens of response room so the model can
        # produce a sensible answer after thinking.
        assert payload["max_tokens"] >= budget + 1024

    def test_already_large_max_tokens_is_preserved(self, adapter):
        # Caller already asked for a big budget — don't shrink it.
        payload = _capture_payload(
            adapter, model="claude-sonnet-4-6", max_tokens=50_000
        )
        assert payload["max_tokens"] == 50_000
        assert payload["max_tokens"] > payload["thinking"]["budget_tokens"]


class TestAdaptiveThinkingModelsUnchanged:
    def test_opus_4_7_gets_no_thinking_block(self, adapter):
        # Opus 4.7 uses adaptive thinking — the adapter must NOT send
        # a thinking block (doing so is a 400 per upstream).
        payload = _capture_payload(
            adapter, model="claude-opus-4-7", max_tokens=20
        )
        assert "thinking" not in payload
        assert payload["max_tokens"] == 20


class TestTemperatureDroppedOnThinking:
    def test_temperature_stripped_when_thinking_enabled(self, adapter):
        # Anthropic requires temperature=1 (or omitted) when thinking
        # is enabled. The adapter drops caller-supplied values silently.
        payload = _capture_payload(
            adapter,
            model="claude-sonnet-4-6",
            max_tokens=20,
            temperature=0.7,
        )
        assert "temperature" not in payload
