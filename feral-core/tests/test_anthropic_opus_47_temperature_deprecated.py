"""Regression test for opus-4-7's deprecated-temperature 400.

Evidence (live smoke against Anthropic on 2026-04-26 with
``claude-opus-4-7``, stream=True, temperature=0.7):

    400 {"type":"error","error":{"type":"invalid_request_error",
    "message":"`temperature` is deprecated for this model."}}

Adaptive-thinking models (currently only ``claude-opus-4-7``) no
longer accept a ``temperature`` parameter. The reasoning fork for
adaptive models must drop ``temperature`` from the payload —
previously it only dropped ``thinking``.

Pins the two sites that build the Anthropic payload:
  * ``providers.anthropic_provider.AnthropicProvider.chat`` (sync)
  * ``agents.llm_provider._apply_anthropic_reasoning_fork`` (stream)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.llm_provider import _apply_anthropic_reasoning_fork
from providers.anthropic_provider import AnthropicProvider
from providers.base import ChatMessage


def _fake_anthropic_200_response():
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {
        "content": [{"type": "text", "text": "ok"}],
        "model": "claude-opus-4-7",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    return m


def _capture_sync_payload(model: str, temperature=None) -> dict:
    adapter = AnthropicProvider(api_key="test-key-do-not-commit")
    with patch(
        "providers.anthropic_provider.httpx.AsyncClient"
    ) as client_cls:
        instance = client_cls.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=_fake_anthropic_200_response())
        asyncio.run(
            adapter.chat(
                messages=[ChatMessage(role="user", content="hi")],
                model=model,
                max_tokens=200,
                temperature=temperature,
            )
        )
        return instance.post.await_args.kwargs["json"]


class TestSyncPath:
    """`AnthropicProvider.chat()` must strip temperature for opus-4-7."""

    def test_opus_4_7_temperature_dropped(self):
        payload = _capture_sync_payload("claude-opus-4-7", temperature=0.7)
        assert "temperature" not in payload, (
            "claude-opus-4-7 rejects any temperature (400 "
            "'temperature is deprecated for this model'); adapter must "
            "drop the caller-supplied value on the adaptive-thinking "
            "branch"
        )
        assert "thinking" not in payload, (
            "Opus 4.7 uses adaptive thinking — explicit thinking block "
            "causes 400 'thinking.type.enabled is not supported'"
        )

    def test_extended_thinking_model_temperature_dropped(self):
        # Extended-thinking models drop temperature too (they require
        # temperature=1 or omitted). Sonnet 4-6 is the canonical case.
        payload = _capture_sync_payload("claude-sonnet-4-6", temperature=0.7)
        assert "temperature" not in payload

    def test_haiku_4_5_temperature_preserved(self):
        # Haiku 4-5 isn't in the adaptive set AND its
        # _default_budget_tokens returns None (thinking off by
        # default). So the fork doesn't fire — temperature passes
        # through unchanged.
        payload = _capture_sync_payload(
            "claude-haiku-4-5-20251001", temperature=0.5
        )
        assert payload.get("temperature") == 0.5


class TestStreamFork:
    """`_apply_anthropic_reasoning_fork` must strip temperature for
    opus-4-7 in the streaming path (llm_provider.py)."""

    def test_opus_4_7_temperature_stripped(self):
        body = {
            "model": "claude-opus-4-7",
            "max_tokens": 1024,
            "temperature": 0.7,
            "messages": [{"role": "user", "content": "hi"}],
        }
        out = _apply_anthropic_reasoning_fork("claude-opus-4-7", body)
        assert "temperature" not in out, (
            "stream path must drop temperature for adaptive-thinking "
            "models; Anthropic 400s on 'temperature is deprecated'"
        )
        assert "thinking" not in out

    def test_opus_4_7_no_existing_temperature_noop(self):
        body = {
            "model": "claude-opus-4-7",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "hi"}],
        }
        out = _apply_anthropic_reasoning_fork("claude-opus-4-7", body)
        assert "temperature" not in out

    def test_non_reasoning_anthropic_model_unchanged(self):
        # claude-3-5-sonnet (non-reasoning) should pass through with
        # temperature preserved.
        body = {
            "model": "claude-3-5-sonnet-20241022",
            "temperature": 0.5,
            "messages": [{"role": "user", "content": "hi"}],
        }
        out = _apply_anthropic_reasoning_fork(
            "claude-3-5-sonnet-20241022", body
        )
        # classify() returns 'chat' not 'reasoning' for 3.x — fork is
        # a no-op.
        assert out.get("temperature") == 0.5
