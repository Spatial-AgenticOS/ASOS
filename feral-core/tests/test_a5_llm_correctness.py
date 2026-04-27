"""A5 — LLM correctness regressions (FERAL audit v2026.5.5).

Covers:

* Failover logging surfaces upstream HTTP body (``error.message``,
  ``type``, ``code``, ``param``) instead of opaque ``str(exception)``.
* ``ProviderCatalog.default_model_for`` refuses completion-only /
  alphabetically-first ids and prefers the recommended shortlist
  for chat defaults.
* ``_build_anthropic_body`` + ``_chat_stream_anthropic`` convert
  OpenAI-style ``role: "tool"`` transcripts and assistant
  ``tool_calls`` to Anthropic's content-block shape.
* The dispatcher enforces
  ``max_tokens > thinking.budget_tokens + 1024`` on Anthropic requests
  (mirrors ``AnthropicProvider.chat``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agents.llm_provider import (
    LLMProvider,
    ProviderCooldownTracker,
    _convert_messages_for_anthropic,
    _enforce_anthropic_thinking_max_tokens,
)
from providers.catalog import ProviderCatalog, CachedModelList


pytestmark = pytest.mark.no_auto_feral_home


# ─────────────────────────────────────────────────────────────────
# 1) Failover error detail surfaces upstream body
# ─────────────────────────────────────────────────────────────────


def _http_status_error(
    status: int = 400,
    payload: dict | None = None,
) -> httpx.HTTPStatusError:
    body_bytes = json.dumps(payload or {}).encode("utf-8")
    response = httpx.Response(
        status_code=status,
        content=body_bytes,
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("expected raise_for_status to fire")


@pytest.mark.asyncio
async def test_failover_warning_includes_provider_body_message(caplog):
    """The primary failover warning must carry the upstream
    ``error.message`` + structured fields so an operator can tell
    ``invalid model`` from ``billing`` from ``context length`` without
    reading downstream logs."""

    llm = LLMProvider.__new__(LLMProvider)
    llm.provider = "openai"
    llm.model = "gpt-5.5"
    llm._config = {"fallback_providers": []}
    llm._local_engine = None
    llm._messages_contain_vision = lambda m: False  # type: ignore
    llm._cooldown = ProviderCooldownTracker()
    llm._build_candidate_list = lambda: [  # type: ignore
        ("openai", {
            "base_url": "https://example.test/v1",
            "api_key": "sk-x",
            "model": "gpt-5.5",
            "supported": True,
        }),
    ]
    upstream_body = {
        "error": {
            "message": "The model 'gpt-5.5' does not exist or you do not have access to it.",
            "type": "invalid_request_error",
            "code": "model_not_found",
            "param": "model",
        }
    }
    exc = _http_status_error(400, upstream_body)
    llm._call_provider = AsyncMock(side_effect=exc)  # type: ignore

    caplog.set_level(logging.WARNING, logger="feral.llm")
    with pytest.raises(httpx.HTTPStatusError):
        await llm.chat_with_failover([{"role": "user", "content": "hi"}])

    matching = [r for r in caplog.records if "Provider openai failed" in r.getMessage()]
    assert matching, "expected a 'Provider <name> failed' warning"
    record = matching[0]
    msg = record.getMessage()
    assert "does not exist" in msg, f"expected upstream message in log, got: {msg}"
    assert "invalid_request_error" in msg
    assert "model_not_found" in msg
    assert record.http_status == 400  # type: ignore[attr-defined]
    assert record.error_type == "invalid_request_error"  # type: ignore[attr-defined]
    assert record.error_code == "model_not_found"  # type: ignore[attr-defined]
    assert record.error_param == "model"  # type: ignore[attr-defined]
    assert "gpt-5.5" in record.body_snippet  # type: ignore[attr-defined]


# ─────────────────────────────────────────────────────────────────
# 2) default_model_for avoids non-chat + alphabetical-first drift
# ─────────────────────────────────────────────────────────────────


def test_default_model_for_openai_skips_babbage(tmp_path):
    cat = ProviderCatalog(cache_path=tmp_path / "cache.json")
    cat._models["openai"] = CachedModelList(
        models=[
            "babbage-002",
            "davinci-002",
            "gpt-4.1",
            "gpt-5.5",
            "gpt-5.5-pro",
            "text-embedding-3-small",
        ],
        last_refresh=0.0,
        source="test",
    )
    default = cat.default_model_for("openai")
    assert default != "babbage-002"
    assert default != "davinci-002"
    assert default != "text-embedding-3-small"
    # Flagship of the recommended shortlist ranks first.
    assert default == "gpt-5.5-pro"


def test_default_model_for_openrouter_skips_ai21(tmp_path):
    cat = ProviderCatalog(cache_path=tmp_path / "cache.json")
    cat._models["openrouter"] = CachedModelList(
        models=[
            "ai21/jamba-large-1.7",
            "anthropic/claude-opus-4-7",
            "openai/gpt-5",
            "openai/o3",
        ],
        last_refresh=0.0,
        source="test",
    )
    default = cat.default_model_for("openrouter")
    assert default != "ai21/jamba-large-1.7"
    # Recommended shortlist prefers Anthropic / OpenAI / Google routes.
    assert default in {
        "anthropic/claude-opus-4-7",
        "openai/gpt-5",
        "openai/o3",
    }


def test_default_model_for_falls_back_to_chat_filter(tmp_path):
    """Provider with no recommended-shortlist hits still returns a
    chat-class model instead of whatever sorted ``[0]`` happens to be."""
    cat = ProviderCatalog(cache_path=tmp_path / "cache.json")
    cat._models["openai"] = CachedModelList(
        models=["babbage-002", "text-embedding-3-small", "gpt-custom-build"],
        last_refresh=0.0,
        source="test",
    )
    default = cat.default_model_for("openai")
    # babbage-002 is completion-only; text-embedding is embedding;
    # gpt-custom-build classifies as chat/unknown and is the correct pick.
    assert default == "gpt-custom-build"


# ─────────────────────────────────────────────────────────────────
# 3) Anthropic message conversion + tool shape
# ─────────────────────────────────────────────────────────────────


def test_convert_tool_role_becomes_user_tool_result_block():
    system, conv = _convert_messages_for_anthropic([
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "list_files",
                        "arguments": '{"path": "/tmp"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": "a.txt\nb.txt",
        },
    ])
    assert system.strip() == "be terse"
    assert len(conv) == 3
    # Assistant turn has a tool_use block, not the raw OpenAI shape.
    assistant = conv[1]
    assert assistant["role"] == "assistant"
    assert isinstance(assistant["content"], list)
    tool_use = next(b for b in assistant["content"] if b["type"] == "tool_use")
    assert tool_use["id"] == "call_abc"
    assert tool_use["name"] == "list_files"
    assert tool_use["input"] == {"path": "/tmp"}
    # Tool result lifted into a user message with a tool_result block.
    tool_msg = conv[2]
    assert tool_msg["role"] == "user"
    assert tool_msg["content"][0]["type"] == "tool_result"
    assert tool_msg["content"][0]["tool_use_id"] == "call_abc"
    assert tool_msg["content"][0]["content"] == "a.txt\nb.txt"
    # Confirm no raw ``role: "tool"`` survived — Anthropic rejects it.
    assert all(m["role"] in ("user", "assistant") for m in conv)


def test_convert_tool_role_missing_id_fails_fast():
    with pytest.raises(ValueError, match="tool_call_id"):
        _convert_messages_for_anthropic([
            {"role": "tool", "content": "orphaned result"},
        ])


def test_build_anthropic_body_bumps_max_tokens_when_thinking_present():
    # A reasoning Claude model with a budget of 16k demands
    # ``max_tokens > 16k``. The dispatcher previously left max_tokens at
    # the default 1024 and Anthropic 400'd.
    body = LLMProvider._build_anthropic_body(  # type: ignore[arg-type]
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.7,
        max_tokens=1024,
    )
    assert "thinking" in body, "extended-thinking model should receive thinking block"
    budget = body["thinking"]["budget_tokens"]
    assert body["max_tokens"] > budget
    assert body["max_tokens"] >= budget + 1024


def test_build_anthropic_body_preserves_large_max_tokens():
    body = LLMProvider._build_anthropic_body(  # type: ignore[arg-type]
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.7,
        max_tokens=100_000,
    )
    assert body["max_tokens"] == 100_000


def test_enforce_anthropic_thinking_noop_without_thinking():
    body = {"max_tokens": 100}
    _enforce_anthropic_thinking_max_tokens(body)
    assert body == {"max_tokens": 100}
