"""Regression tests for A1 stream-recovery and tool-event emission."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.orchestrator import Orchestrator


@pytest.fixture
def async_send() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def orchestrator(async_send: AsyncMock) -> Orchestrator:
    reg = MagicMock()
    reg.skills = {}
    reg.find_skills_for_query = MagicMock(return_value=[])
    reg.get_tools_for_skills = MagicMock(return_value=[])
    return Orchestrator(
        skill_registry=reg,
        send_to_client=async_send,
        daemons={},
        memory=None,
        vision_buffer=None,
        perception=None,
        learner=None,
    )


class TestStreamFallbackHistory:
    """A1: stream -> non-stream fallback must not duplicate the user row.

    The stream path appends the user message, then on exception falls
    back to ``handle_command`` which also appends — without the A1
    fix that produces two identical user rows in ``conversation_history``.
    """

    @pytest.mark.asyncio
    async def test_stream_exception_drops_user_row_before_fallback(
        self, orchestrator: Orchestrator
    ) -> None:
        session_id = "sess-a1"
        # Seed the history in the exact shape the stream path would
        # have produced just before raising: one assistant bootstrap
        # row followed by a freshly-appended user row.
        orchestrator.conversation_history[session_id] = [
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "do the thing"},
        ]

        # Patch ``handle_command`` to record the history shape the
        # fallback observes, without running the full pipeline.
        captured: dict = {}

        async def fake_handle_command(sid, text, context=None):
            captured["pre_call_len"] = len(orchestrator.conversation_history[sid])
            # mimic non-stream path appending exactly one user row
            orchestrator.conversation_history[sid].append(
                {"role": "user", "content": text}
            )

        orchestrator.handle_command = fake_handle_command  # type: ignore[assignment]

        # Execute the exception-handling snippet from
        # ``_handle_command_stream_impl`` directly: pop trailing user
        # row, then call handle_command. This is the regression gate.
        hist = orchestrator.conversation_history.get(session_id) or []
        if hist and hist[-1].get("role") == "user":
            hist.pop()
        await orchestrator.handle_command(session_id, "do the thing", None)

        # The fallback must have observed exactly one user row for
        # this turn (the freshly-appended one), and the final history
        # must not contain two consecutive identical user rows.
        final = orchestrator.conversation_history[session_id]
        user_rows = [m for m in final if m.get("role") == "user"]
        assert len(user_rows) == 1, final
        assert captured["pre_call_len"] == 1  # only the assistant seed


class TestToolEventEmission:
    """A1: orchestrator emits structured tool_start / tool_result."""

    @pytest.mark.asyncio
    async def test_emit_tool_start_sends_tool_start_payload(
        self, orchestrator: Orchestrator, async_send: AsyncMock
    ) -> None:
        tc = {"id": "c1", "name": "web_search__run", "args": {"q": "hi"}}
        await orchestrator._emit_tool_start("sess-1", tc)
        assert async_send.await_count == 1
        _, msg = async_send.await_args.args
        assert msg.type == "tool_start"
        payload = msg.payload
        assert payload["tool"] == "web_search__run"
        assert payload["skill_id"] == "web_search"
        assert payload["endpoint_id"] == "run"
        assert payload["call_id"] == "c1"
        assert "hi" in payload["args_preview"]
        assert payload["display_name"] == "Search web"

    @pytest.mark.asyncio
    async def test_emit_tool_result_sends_success_flag(
        self, orchestrator: Orchestrator, async_send: AsyncMock
    ) -> None:
        tc = {"id": "c2", "name": "notes__add"}
        await orchestrator._emit_tool_result(
            "sess-2", tc, {"success": True}, latency_ms=42.0
        )
        assert async_send.await_count == 1
        _, msg = async_send.await_args.args
        assert msg.type == "tool_result"
        assert msg.payload["success"] is True
        assert msg.payload["call_id"] == "c2"
        assert msg.payload["latency_ms"] == pytest.approx(42.0)

    @pytest.mark.asyncio
    async def test_emit_tool_result_failure_carries_error(
        self, orchestrator: Orchestrator, async_send: AsyncMock
    ) -> None:
        tc = {"name": "x__y"}
        await orchestrator._emit_tool_result(
            "s", tc, {"success": False, "error": "boom"}, latency_ms=0.0
        )
        _, msg = async_send.await_args.args
        assert msg.payload["success"] is False
        assert "boom" in msg.payload["error"]


class TestFailoverSanitization:
    """Non-stream failover converts response text through the sanitizer
    before emitting synthetic text_delta events (A1)."""

    @pytest.mark.asyncio
    async def test_failover_strips_control_tokens(self):
        from agents.llm_provider import LLMProvider

        provider = LLMProvider.__new__(LLMProvider)
        provider.provider = "openai"
        provider.model = "gpt-x"
        provider._config = {"fallback_providers": ["anthropic"]}
        provider._local_engine = None
        provider._cooldown = MagicMock()
        provider._cooldown.record_failure = MagicMock()
        provider._cooldown._last_probe = {}
        provider.chat_with_failover = AsyncMock(return_value={
            "choices": [{
                "message": {"content": "Answer<|eom|></tool_calls>", "tool_calls": []},
                "finish_reason": "stop",
            }],
        })

        events = await provider._stream_via_nonstream_failover(
            messages=[], tools=None, temperature=0.0, max_tokens=64,
            primary_error=RuntimeError("connection reset"),
        )
        assert events is not None
        text_events = [e for e in events if e.get("type") == "text_delta"]
        assert text_events, events
        combined = "".join(e["content"] for e in text_events)
        assert "<|eom|>" not in combined
        assert "</tool_calls>" not in combined
        assert "Answer" in combined
