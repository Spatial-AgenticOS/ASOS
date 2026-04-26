"""DeepSeek ``reasoning_content`` multi-turn carry contract tests.

Upstream rule (2026-04-26 pricing + thinking-mode docs):

* When a thinking-mode turn emits a tool call, the next turn MUST
  replay the assistant message WITH ``reasoning_content`` intact —
  otherwise the API returns 400 "reasoning_content missing".
* When a thinking-mode turn completes (no tool call follow-up), the
  next turn's replayed assistant message SHOULD drop
  ``reasoning_content`` — leaving it causes the model to re-emit
  reasoning tokens on an already-answered turn, bloating context.

``providers.deepseek_provider.carry_reasoning_content`` encodes these
two branches. This test pins them so a refactor can't silently regress
the contract.
"""

from __future__ import annotations

import pytest

from providers.deepseek_provider import (
    carry_reasoning_content,
    strip_reasoning_content_for_non_tool_turn,
)


# ---------------------------------------------------------------------------
# carry_reasoning_content
# ---------------------------------------------------------------------------


class TestMultiTurnCarry:
    def test_tool_call_turn_preserves_reasoning_content(self) -> None:
        """Assistant emitted a tool call → next request MUST carry
        reasoning_content on the replayed assistant message."""
        replay = [
            {"role": "user", "content": "what's the weather in Paris?"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "need to call weather tool",
                "tool_calls": [
                    {"id": "tc_1", "type": "function",
                     "function": {"name": "weather", "arguments": "{\"city\":\"Paris\"}"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc_1",
                "content": "18C, partly cloudy",
            },
        ]
        carried = carry_reasoning_content(replay)
        assistant = [m for m in carried if m.get("role") == "assistant"][-1]
        assert "reasoning_content" in assistant, (
            "Dropping reasoning_content on a tool-cycle turn is the exact "
            "shape of DeepSeek's 400 'reasoning_content missing'"
        )
        assert assistant["reasoning_content"] == "need to call weather tool"

    def test_non_tool_turn_strips_reasoning_content(self) -> None:
        """Assistant answered (no tool) → next request MUST drop
        reasoning_content from the replayed assistant message."""
        replay = [
            {"role": "user", "content": "capital of France?"},
            {
                "role": "assistant",
                "content": "Paris.",
                "reasoning_content": "recall geography facts; answer is Paris",
            },
            {"role": "user", "content": "thanks"},
        ]
        carried = carry_reasoning_content(replay)
        assistant = [m for m in carried if m.get("role") == "assistant"][0]
        assert "reasoning_content" not in assistant, (
            "Leaving reasoning_content on a non-tool turn inflates context "
            "and causes the model to regenerate reasoning tokens"
        )

    def test_strip_helper_is_mutation_free(self) -> None:
        """The strip helper returns a fresh dict; input is untouched."""
        original = {"role": "assistant", "content": "x", "reasoning_content": "y"}
        stripped = strip_reasoning_content_for_non_tool_turn(original)
        assert "reasoning_content" in original, "helper must not mutate input"
        assert "reasoning_content" not in stripped

    def test_empty_replay_is_noop(self) -> None:
        assert carry_reasoning_content([]) == []

    def test_replay_with_no_assistant_is_noop(self) -> None:
        replay = [{"role": "user", "content": "hi"}]
        assert carry_reasoning_content(replay) == replay

    def test_strip_on_message_without_reasoning_content(self) -> None:
        msg = {"role": "assistant", "content": "x"}
        assert strip_reasoning_content_for_non_tool_turn(msg) is msg or \
               strip_reasoning_content_for_non_tool_turn(msg) == msg
