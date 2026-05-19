"""Tests for audit-r12 D8: real Bedrock Converse provider.

Pre-r12 ``BedrockProvider.chat`` raised ``RuntimeError(... stub
level ...)`` unconditionally — anyone who picked Bedrock in the
wizard crashed on first message. This suite pins the new behaviour
without ever touching a real AWS account:

* Request shapes are asserted at the boto-client boundary (the
  Converse API is normalised across families, so a single shape
  check covers Anthropic / Meta / Mistral on Bedrock).
* The ChatResponse translation is unit-tested against the official
  Converse response shape from the AWS docs.
* Streaming, validation, and the no-stub guarantee are pinned.

A live integration test exists for the BEDROCK_LIVE=1 case (skipped
by default — gated on real credentials being present).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

_FERAL_CORE = Path(__file__).resolve().parent.parent
if str(_FERAL_CORE) not in sys.path:
    sys.path.insert(0, str(_FERAL_CORE))

from providers.base import ChatMessage  # noqa: E402
from providers.bedrock_provider import (  # noqa: E402
    BedrockProvider,
    _converse_response_to_chat_response,
    _messages_to_converse,
    _tools_to_converse,
)


# ─────────────────────────────────────────────
# Pure shape translations — no boto needed
# ─────────────────────────────────────────────


def test_messages_to_converse_extracts_system_blocks():
    msgs = [
        ChatMessage(role="system", content="You are a helpful AI"),
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi there"),
    ]
    converse, system = _messages_to_converse(msgs)
    assert system == [{"text": "You are a helpful AI"}]
    assert converse == [
        {"role": "user", "content": [{"text": "Hello"}]},
        {"role": "assistant", "content": [{"text": "Hi there"}]},
    ]


def test_messages_to_converse_translates_tool_results():
    msgs = [
        ChatMessage(role="user", content="What's 2+2?"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[{"id": "tu_1", "name": "calc", "input": {"expr": "2+2"}}],
        ),
        ChatMessage(role="tool", name="tu_1", content="4"),
    ]
    converse, system = _messages_to_converse(msgs)
    assert system == []
    assert converse[0]["role"] == "user"
    assert converse[1]["role"] == "assistant"
    # Tool-use content block comes through unchanged.
    tool_use = converse[1]["content"][0]["toolUse"]
    assert tool_use["toolUseId"] == "tu_1"
    assert tool_use["name"] == "calc"
    # Tool RESULT is rendered as a user-role toolResult block per
    # Converse API rules.
    assert converse[2]["role"] == "user"
    tool_result = converse[2]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "tu_1"
    assert tool_result["content"][0]["text"] == "4"


def test_tools_to_converse_wraps_inputschema_in_json_key():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Look up the weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
    ]
    out = _tools_to_converse(tools)
    assert out is not None
    spec = out["tools"][0]["toolSpec"]
    assert spec["name"] == "get_weather"
    # The Converse spec wraps the JSON schema under a ``json`` key —
    # this is the gotcha that breaks vendors who skip the live docs.
    assert "json" in spec["inputSchema"]
    assert spec["inputSchema"]["json"]["type"] == "object"


def test_tools_to_converse_returns_none_for_empty_tools():
    # Bedrock 400s on an empty toolConfig — never send one.
    assert _tools_to_converse(None) is None
    assert _tools_to_converse([]) is None


def test_converse_response_to_chat_response_collects_text_and_tool_calls():
    resp = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"text": "I'll look it up. "},
                    {
                        "toolUse": {
                            "toolUseId": "tu_99",
                            "name": "get_weather",
                            "input": {"city": "Reykjavik"},
                        }
                    },
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 14, "outputTokens": 23, "totalTokens": 37},
    }
    out = _converse_response_to_chat_response(resp, model="anthropic.claude-3-5-sonnet")
    assert out.text == "I'll look it up. "
    assert out.finish_reason == "tool_use"
    assert out.usage == {"input_tokens": 14, "output_tokens": 23, "total_tokens": 37}
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0] == {
        "id": "tu_99",
        "name": "get_weather",
        "input": {"city": "Reykjavik"},
    }


# ─────────────────────────────────────────────
# chat() — boto3 client is mocked at the method boundary
# ─────────────────────────────────────────────


class _StubBedrockRuntime:
    """Captures Converse requests and returns a canned response.

    Used in place of a real boto3 client. ``converse`` is sync (the
    real client is sync), ``converse_stream`` returns a dict with a
    ``stream`` iterator of event dicts."""

    def __init__(self) -> None:
        self.converse_requests: list[dict] = []
        self.converse_response: dict = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "hello back"}],
                }
            },
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 3, "totalTokens": 8},
        }
        self.stream_requests: list[dict] = []
        self.stream_events: list[dict] = [
            {"contentBlockDelta": {"delta": {"text": "stream "}}},
            {"contentBlockDelta": {"delta": {"text": "chunk"}}},
        ]

    def converse(self, **kwargs: Any) -> dict:
        self.converse_requests.append(kwargs)
        return self.converse_response

    def converse_stream(self, **kwargs: Any) -> dict:
        self.stream_requests.append(kwargs)
        return {"stream": iter(self.stream_events)}


@pytest.mark.asyncio
async def test_chat_real_request_shape_no_stub_raise():
    prov = BedrockProvider(region="us-east-1")
    stub = _StubBedrockRuntime()
    prov._runtime_client = stub  # bypass boto3 import for the test

    resp = await prov.chat(
        [
            ChatMessage(role="system", content="be brief"),
            ChatMessage(role="user", content="hi"),
        ],
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        max_tokens=128,
        temperature=0.5,
    )
    # CRITICAL: not a RuntimeError stub — a real response.
    assert resp.text == "hello back"
    assert resp.usage == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
    # Pin the exact Converse request shape so a regression that drops
    # ``inferenceConfig`` (or sends Claude-specific Anthropic JSON
    # instead of normalised Converse) fails this test loudly.
    assert len(stub.converse_requests) == 1
    req = stub.converse_requests[0]
    assert req["modelId"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert req["system"] == [{"text": "be brief"}]
    assert req["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]
    assert req["inferenceConfig"] == {"maxTokens": 128, "temperature": 0.5}
    # No toolConfig when tools=None — Bedrock 400s on an empty one.
    assert "toolConfig" not in req


@pytest.mark.asyncio
async def test_chat_sends_toolconfig_when_tools_provided():
    prov = BedrockProvider()
    stub = _StubBedrockRuntime()
    prov._runtime_client = stub
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        }
    ]
    await prov.chat(
        [ChatMessage(role="user", content="search for cats")],
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        tools=tools,
    )
    req = stub.converse_requests[0]
    assert "toolConfig" in req
    assert req["toolConfig"]["tools"][0]["toolSpec"]["name"] == "search_web"


@pytest.mark.asyncio
async def test_chat_propagates_boto_failure_as_runtime_error():
    # botocore raises ClientError subclasses; we model that here with a
    # plain Exception subclass so the test isn't tied to boto3 being
    # installed.
    class _BotoLikeClientError(Exception):
        pass

    class _FailingClient:
        def converse(self, **kwargs):
            raise _BotoLikeClientError("AccessDeniedException")

    prov = BedrockProvider()
    prov._runtime_client = _FailingClient()
    with pytest.raises(RuntimeError, match="bedrock converse failed"):
        await prov.chat(
            [ChatMessage(role="user", content="hi")],
            model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        )


# ─────────────────────────────────────────────
# stream_chat() — converse_stream
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_chat_yields_text_deltas():
    prov = BedrockProvider()
    stub = _StubBedrockRuntime()
    prov._runtime_client = stub
    gen = await prov.stream_chat(
        [ChatMessage(role="user", content="hi")],
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
    )
    chunks = [chunk async for chunk in gen]
    assert chunks == ["stream ", "chunk"]
    # Pin the request shape on the streaming path too.
    assert stub.stream_requests[0]["modelId"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"


# ─────────────────────────────────────────────
# validate_credentials — wizard pre-flight
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_credentials_returns_true_on_success():
    class _ControlClient:
        def list_foundation_models(self):
            return {"modelSummaries": [{"modelId": "x"}]}

    prov = BedrockProvider()
    prov._control_client = _ControlClient()
    assert await prov.validate_credentials() is True


@pytest.mark.asyncio
async def test_validate_credentials_returns_false_on_aws_error():
    class _FailingControlClient:
        def list_foundation_models(self):
            raise RuntimeError("UnrecognizedClientException")

    prov = BedrockProvider()
    prov._control_client = _FailingControlClient()
    assert await prov.validate_credentials() is False


def test_provider_is_no_longer_stub():
    # audit-r12 D8 invariant: ``chat_ready`` MUST be True and
    # ``stub_reason`` MUST be empty so the catalog renders Bedrock as
    # ready. Pre-r12 these were False/"stub level" which is what the
    # audit complained about.
    prov = BedrockProvider()
    assert prov.chat_ready is True
    assert prov.stub_reason == ""


# ─────────────────────────────────────────────
# Live integration test — gated by BEDROCK_LIVE=1
# ─────────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("BEDROCK_LIVE") != "1",
    reason="set BEDROCK_LIVE=1 + AWS creds to run the live Bedrock test",
)
@pytest.mark.asyncio
async def test_live_chat_round_trip():
    prov = BedrockProvider()
    assert await prov.validate_credentials() is True, "AWS credentials lack Bedrock entitlement"
    resp = await prov.chat(
        [ChatMessage(role="user", content="Say 'pong' in one word.")],
        model=os.environ.get(
            "BEDROCK_LIVE_MODEL",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
        ),
        max_tokens=20,
    )
    assert resp.text.strip().lower().startswith("pong")
    assert resp.usage["input_tokens"] > 0
    