"""v2026.5.23 — Responses API adapter + classifier_endpoint + probe + tool-gate.

Six concerns under test, scoped to the audit-r10 launch fix that closes the
operator's blocked-chat report (gpt-5.5-pro 404 on /v1/chat/completions):

1.  ``providers.model_classes.classify_endpoint`` returns ``"responses"`` for
    OpenAI Pro / o-series Pro / deep-research / Codex / computer-use models
    and ``"chat_completions"`` for everything else.
2.  ``is_responses_only`` delegates correctly through OpenRouter vendor
    prefix.
3.  ``apply_responses_param_fork`` renames ``max_tokens`` →
    ``max_output_tokens``, nests reasoning under an object, drops
    chat-shaped sampling params.
4.  ``LLMProvider._build_responses_body`` produces the canonical
    Responses-API body shape (``input`` not ``messages``, ``instructions``
    from the first system message, function tools flattened, reasoning
    nested).
5.  ``LLMProvider._messages_to_responses_input`` round-trips tool-call
    history (assistant ``tool_calls`` → ``function_call`` items; tool
    role → ``function_call_output``).
6.  ``ToolRunner._notify_user_of_pending_approval`` emits a user-visible
    chat line via ``orchestrator._send_text`` when an LLM-loop tool call
    hits ``pending_approval`` — closing the silent-frozen-turn bug.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── classify_endpoint + is_responses_only ───────────────────────


class TestClassifyEndpoint:
    def test_gpt_5_5_pro_routes_to_responses(self):
        from providers.model_classes import classify_endpoint, is_responses_only

        assert classify_endpoint("openai", "gpt-5.5-pro") == "responses"
        assert is_responses_only("openai", "gpt-5.5-pro") is True

    def test_gpt_5_pro_dated_snapshot_routes_to_responses(self):
        from providers.model_classes import classify_endpoint

        assert classify_endpoint("openai", "gpt-5-pro-2026-05-08") == "responses"

    def test_o3_pro_routes_to_responses(self):
        from providers.model_classes import classify_endpoint

        assert classify_endpoint("openai", "o3-pro") == "responses"

    def test_deep_research_routes_to_responses(self):
        from providers.model_classes import classify_endpoint

        assert classify_endpoint("openai", "gpt-5.5-deep-research") == "responses"
        assert classify_endpoint("openai", "o3-deep-research-mini") == "responses"

    def test_codex_and_computer_use_route_to_responses(self):
        from providers.model_classes import classify_endpoint

        assert classify_endpoint("openai", "gpt-5-codex") == "responses"
        assert classify_endpoint("openai", "computer-use-preview") == "responses"

    def test_non_pro_reasoning_stays_chat_completions(self):
        # gpt-5.5 (no -pro), o3, o4-mini — work fine on /v1/chat/completions
        # AND /v1/responses; FERAL keeps them on chat-completions so the
        # adapter swap doesn't silently reroute traffic that was working.
        from providers.model_classes import classify_endpoint

        assert classify_endpoint("openai", "gpt-5.5") == "chat_completions"
        assert classify_endpoint("openai", "gpt-5.4") == "chat_completions"
        assert classify_endpoint("openai", "o3") == "chat_completions"
        assert classify_endpoint("openai", "o4-mini") == "chat_completions"

    def test_plain_chat_models_stay_chat_completions(self):
        from providers.model_classes import classify_endpoint

        assert classify_endpoint("openai", "gpt-4o") == "chat_completions"
        assert classify_endpoint("openai", "gpt-4.1") == "chat_completions"
        assert classify_endpoint("openai", "gpt-3.5-turbo") == "chat_completions"

    def test_openrouter_openai_pro_delegates(self):
        from providers.model_classes import classify_endpoint, is_responses_only

        assert classify_endpoint("openrouter", "openai/gpt-5.5-pro") == "responses"
        assert is_responses_only("openrouter", "openai/gpt-5.5-pro") is True

    def test_openrouter_openai_non_pro_stays_chat(self):
        from providers.model_classes import classify_endpoint

        assert classify_endpoint("openrouter", "openai/gpt-5.5") == "chat_completions"
        assert classify_endpoint("openrouter", "openai/gpt-5.5:nitro") == "chat_completions"

    def test_openrouter_non_openai_never_responses_only(self):
        from providers.model_classes import classify_endpoint

        assert classify_endpoint(
            "openrouter", "anthropic/claude-opus-4-7"
        ) == "chat_completions"
        assert classify_endpoint(
            "openrouter", "deepseek/deepseek-v4-pro"
        ) == "chat_completions"

    def test_anthropic_models_never_responses_only(self):
        # Anthropic uses /v1/messages, not /v1/responses. We never route
        # Anthropic traffic through the Responses adapter regardless of
        # extended-thinking status.
        from providers.model_classes import classify_endpoint, is_responses_only

        assert classify_endpoint("anthropic", "claude-opus-4-7") == "chat_completions"
        assert is_responses_only("anthropic", "claude-opus-4-7") is False

    def test_unknown_model_defaults_to_chat_completions(self):
        from providers.model_classes import classify_endpoint

        # Frontier id not in any rule — default-include for chat, never
        # silently route to /v1/responses (would 404 if the model
        # doesn't actually exist on that endpoint).
        assert classify_endpoint("openai", "gpt-6-mystery") == "chat_completions"
        assert classify_endpoint("openai", "") == "chat_completions"


# ─── apply_responses_param_fork ──────────────────────────────────


class TestResponsesParamFork:
    def test_renames_max_tokens(self):
        from agents.llm_reasoning import apply_responses_param_fork

        body = {"max_tokens": 256, "temperature": 1, "messages": [...]}
        apply_responses_param_fork("gpt-5.5-pro", body)
        assert "max_tokens" not in body
        assert body["max_output_tokens"] == 256

    def test_renames_max_completion_tokens(self):
        # When the caller already ran the chat-completions reasoning
        # fork before realising the endpoint should be Responses,
        # the rename target shifts again.
        from agents.llm_reasoning import apply_responses_param_fork

        body = {"max_completion_tokens": 512}
        apply_responses_param_fork("gpt-5.5-pro", body)
        assert "max_completion_tokens" not in body
        assert body["max_output_tokens"] == 512

    def test_nests_reasoning_effort(self):
        from agents.llm_reasoning import apply_responses_param_fork

        body = {"max_tokens": 1, "reasoning_effort": "high"}
        apply_responses_param_fork("gpt-5.5-pro", body)
        assert body["reasoning"] == {"effort": "high"}
        assert "reasoning_effort" not in body

    def test_default_effort_is_medium(self):
        from agents.llm_reasoning import apply_responses_param_fork

        body = {"max_tokens": 1}
        apply_responses_param_fork("gpt-5.5-pro", body)
        assert body["reasoning"]["effort"] == "medium"

    def test_drops_chat_sampling_params(self):
        from agents.llm_reasoning import apply_responses_param_fork

        body = {
            "max_tokens": 10,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.5,
            "frequency_penalty": 0.5,
        }
        apply_responses_param_fork("gpt-5.5-pro", body)
        for k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
            assert k not in body, f"{k} should be dropped from Responses body"

    def test_preserves_existing_reasoning_dict(self):
        from agents.llm_reasoning import apply_responses_param_fork

        body = {"reasoning": {"effort": "xhigh", "extra": "passthrough"}}
        apply_responses_param_fork("gpt-5.5-pro", body)
        assert body["reasoning"]["effort"] == "xhigh"
        assert body["reasoning"]["extra"] == "passthrough"


# ─── _messages_to_responses_input + _chat_tools_to_responses_tools ─


class TestResponsesMessageTranslation:
    def test_first_system_becomes_instructions(self):
        from agents.llm_provider import LLMProvider

        msgs = [
            {"role": "system", "content": "You are FERAL."},
            {"role": "user", "content": "Hi"},
        ]
        instructions, items = LLMProvider._messages_to_responses_input(msgs)
        assert instructions == "You are FERAL."
        assert items == [{"role": "user", "content": "Hi"}]

    def test_second_system_becomes_user_item(self):
        # First system wins as instructions; later ones aren't silently
        # lost — they become user-role items so PromptRefiner-style
        # additional system notes still reach the model.
        from agents.llm_provider import LLMProvider

        msgs = [
            {"role": "system", "content": "primary"},
            {"role": "system", "content": "appendix"},
            {"role": "user", "content": "hi"},
        ]
        instructions, items = LLMProvider._messages_to_responses_input(msgs)
        assert instructions == "primary"
        assert items[0] == {"role": "user", "content": "appendix"}

    def test_tool_role_becomes_function_call_output(self):
        from agents.llm_provider import LLMProvider

        msgs = [
            {"role": "user", "content": "do it"},
            {"role": "tool", "tool_call_id": "call_abc", "content": '{"ok":true}'},
        ]
        _, items = LLMProvider._messages_to_responses_input(msgs)
        assert items[1] == {
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": '{"ok":true}',
        }

    def test_assistant_tool_calls_become_function_call_items(self):
        from agents.llm_provider import LLMProvider

        msgs = [
            {"role": "user", "content": "do it"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_xyz",
                        "function": {"name": "do_thing", "arguments": '{"x":1}'},
                    }
                ],
            },
        ]
        _, items = LLMProvider._messages_to_responses_input(msgs)
        function_call_items = [i for i in items if i.get("type") == "function_call"]
        assert len(function_call_items) == 1
        assert function_call_items[0]["call_id"] == "call_xyz"
        assert function_call_items[0]["name"] == "do_thing"
        assert function_call_items[0]["arguments"] == '{"x":1}'

    def test_chat_tools_flatten_to_responses_shape(self):
        from agents.llm_provider import LLMProvider

        chat_tools = [
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "description": "say hi",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        out = LLMProvider._chat_tools_to_responses_tools(chat_tools)
        assert out == [
            {
                "type": "function",
                "name": "ping",
                "description": "say hi",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

    def test_chat_tools_none_passes_through(self):
        from agents.llm_provider import LLMProvider

        assert LLMProvider._chat_tools_to_responses_tools(None) is None
        assert LLMProvider._chat_tools_to_responses_tools([]) is None


# ─── _build_responses_body ────────────────────────────────────────


class TestBuildResponsesBody:
    def _provider(self):
        from agents.llm_provider import LLMProvider

        p = LLMProvider.__new__(LLMProvider)
        p.provider = "openai"
        p.model = "gpt-5.5-pro"
        return p

    def test_canonical_streaming_body(self):
        p = self._provider()
        body = p._build_responses_body(
            [
                {"role": "system", "content": "FERAL system prompt."},
                {"role": "user", "content": "Hi"},
            ],
            tools=None,
            temperature=1,
            max_tokens=128,
            stream=True,
        )
        assert body["model"] == "gpt-5.5-pro"
        # Chat 'messages' must not leak; Responses uses 'input'.
        assert "messages" not in body
        assert "input" in body
        assert body["instructions"] == "FERAL system prompt."
        assert body["stream"] is True
        assert body["max_output_tokens"] == 128
        assert body["reasoning"] == {"effort": "medium"}

    def test_temperature_07_dropped_for_pro(self):
        # Pro models reject temperature != 1; the param fork strips it.
        p = self._provider()
        body = p._build_responses_body(
            [{"role": "user", "content": "hi"}],
            tools=None, temperature=0.7, max_tokens=64, stream=False,
        )
        assert "temperature" not in body

    def test_tools_translate_to_flat_shape(self):
        p = self._provider()
        body = p._build_responses_body(
            [{"role": "user", "content": "do it"}],
            tools=[{
                "type": "function",
                "function": {"name": "do_thing", "description": "", "parameters": {}},
            }],
            temperature=1, max_tokens=32, stream=False,
        )
        assert body["tool_choice"] == "auto"
        assert body["tools"] == [{
            "type": "function", "name": "do_thing",
            "description": "", "parameters": {},
        }]


# ─── _responses_payload_to_chat_dict ─────────────────────────────


class TestResponsesPayloadNormalisation:
    def test_text_output_round_trips_to_chat_shape(self):
        from agents.llm_provider import LLMProvider

        payload = {
            "id": "resp_123",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Hello "},
                        {"type": "output_text", "text": "world."},
                    ],
                }
            ],
            "status": "completed",
        }
        result = LLMProvider._responses_payload_to_chat_dict(payload)
        assert result["choices"][0]["message"]["content"] == "Hello world."
        assert result["choices"][0]["message"]["role"] == "assistant"
        assert result.get("_responses_id") == "resp_123"

    def test_function_call_output_translates(self):
        from agents.llm_provider import LLMProvider

        payload = {
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_abc",
                    "name": "do_thing",
                    "arguments": '{"x": 1}',
                }
            ],
        }
        result = LLMProvider._responses_payload_to_chat_dict(payload)
        tool_calls = result["choices"][0]["message"]["tool_calls"]
        assert tool_calls[0]["id"] == "call_abc"
        assert tool_calls[0]["function"]["name"] == "do_thing"
        assert json.loads(tool_calls[0]["function"]["arguments"]) == {"x": 1}

    def test_error_payload_surfaces_as_error_dict(self):
        from agents.llm_provider import LLMProvider

        payload = {"error": {"message": "model_not_found"}}
        result = LLMProvider._responses_payload_to_chat_dict(payload)
        assert "model_not_found" in result["error"]
        assert result["choices"] == []


# ─── ToolRunner pending-approval notification ────────────────────


@pytest.mark.asyncio
async def test_notify_user_of_pending_approval_calls_send_text():
    from agents.tool_runner import ToolRunner

    orch = SimpleNamespace()
    sent: list[tuple[str, str]] = []

    async def fake_send_text(sid, text):
        sent.append((sid, text))
    orch._send_text = fake_send_text

    runner = ToolRunner.__new__(ToolRunner)
    runner._orch = orch

    await runner._notify_user_of_pending_approval(
        "primary-x",
        "computer_use__write_file",
        {
            "status": "pending_approval",
            "tool_name": "computer_use__write_file",
            "request_id": "req-abc",
            "safety_level": "confirm",
        },
    )

    assert sent, "_send_text was not called"
    sid, text = sent[0]
    assert sid == "primary-x"
    assert "computer_use__write_file" in text
    assert "req-abc" in text


@pytest.mark.asyncio
async def test_notify_user_skips_for_non_pending():
    # Non-pending denials (e.g. hard denial) don't trigger the chat
    # notification — they have their own error pathway.
    from agents.tool_runner import ToolRunner

    orch = SimpleNamespace()
    sent: list = []
    async def fake_send_text(sid, text): sent.append((sid, text))
    orch._send_text = fake_send_text

    runner = ToolRunner.__new__(ToolRunner)
    runner._orch = orch

    await runner._notify_user_of_pending_approval(
        "primary-x",
        "computer_use__rm_rf",
        {"status": "denied", "tool_name": "computer_use__rm_rf"},
    )
    assert sent == []


@pytest.mark.asyncio
async def test_notify_user_swallows_send_text_failures():
    from agents.tool_runner import ToolRunner

    orch = SimpleNamespace()
    async def boom(sid, text): raise RuntimeError("socket closed")
    orch._send_text = boom

    runner = ToolRunner.__new__(ToolRunner)
    runner._orch = orch

    # Must not raise even when send_text fails — pending_approval flow
    # is best-effort; orchestrator must not crash on user-notification
    # transport error.
    await runner._notify_user_of_pending_approval(
        "primary-x", "x", {"status": "pending_approval", "request_id": "r"},
    )


# ─── _probe_chat_availability (round-trip semantics) ─────────────


@pytest.mark.asyncio
async def test_probe_uses_responses_endpoint_for_pro_models():
    from agents.llm_provider import LLMProvider

    p = LLMProvider.__new__(LLMProvider)
    p.provider = "openai"
    p.model = "gpt-5.5-pro"

    # Mock httpx client. Probe should POST to /responses.
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    p.client = MagicMock()
    p.client.post = AsyncMock(return_value=mock_resp)

    ok, reason = await p._probe_chat_availability()
    assert ok is True
    assert reason == ""
    # Confirm the right endpoint was hit.
    called_path = p.client.post.call_args[0][0]
    assert called_path == "/responses"


@pytest.mark.asyncio
async def test_probe_uses_chat_completions_endpoint_for_non_pro():
    from agents.llm_provider import LLMProvider

    p = LLMProvider.__new__(LLMProvider)
    p.provider = "openai"
    p.model = "gpt-5.4"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    p.client = MagicMock()
    p.client.post = AsyncMock(return_value=mock_resp)

    ok, _ = await p._probe_chat_availability()
    assert ok is True
    called_path = p.client.post.call_args[0][0]
    assert called_path == "/chat/completions"


@pytest.mark.asyncio
async def test_probe_returns_structured_failure_on_404():
    from agents.llm_provider import LLMProvider

    p = LLMProvider.__new__(LLMProvider)
    p.provider = "openai"
    p.model = "gpt-5.4"

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json = MagicMock(return_value={
        "error": {"message": "This is not a chat model."},
    })
    p.client = MagicMock()
    p.client.post = AsyncMock(return_value=mock_resp)

    ok, reason = await p._probe_chat_availability()
    assert ok is False
    assert "404" in reason
    assert "not a chat model" in reason
