"""
Tests for agents/digital_twin.py — DigitalTwin init, ask(), predict_preference(),
daily_reflection(), and helper methods.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.digital_twin import DigitalTwin


@pytest.fixture
def twin():
    memory = MagicMock()
    memory.episode_recent.return_value = []
    memory.search.return_value = []
    memory.knowledge_search.return_value = []

    identity = MagicMock()
    identity.load_identity.return_value = "You are Alex. A software engineer who loves coffee."

    llm = AsyncMock()
    llm.chat.return_value = {"choices": [{"message": {"content": "Mocked LLM answer", "tool_calls": []}}]}
    llm.extract_response = MagicMock(return_value=("Mocked LLM answer", []))

    return DigitalTwin(memory=memory, identity_loader=identity, llm=llm)


class TestDigitalTwinInit:
    def test_has_expected_deps(self, twin):
        assert twin._memory is not None
        assert twin._identity is not None
        assert twin._llm is not None


class TestAsk:
    @pytest.mark.asyncio
    async def test_ask_calls_llm(self, twin):
        result = await twin.ask("What's my favorite language?", session_id="s1")
        assert result == "Mocked LLM answer"
        twin._llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ask_with_dict_response(self, twin):
        twin._llm.chat.return_value = {"choices": [{"message": {"content": "dict answer", "tool_calls": []}}]}
        twin._llm.extract_response = MagicMock(return_value=("dict answer", []))
        result = await twin.ask("question")
        assert result == "dict answer"

    @pytest.mark.asyncio
    async def test_ask_handles_llm_error(self, twin):
        twin._llm.chat.side_effect = RuntimeError("boom")
        result = await twin.ask("fail question")
        # Commit 5 changed the fallback message to point the user at
        # Settings → Providers so they know where to fix it. Keep the
        # assertion on the stable "Configure" wording.
        assert "Configure a working provider" in result


class TestPredictPreference:
    @pytest.mark.asyncio
    async def test_no_memories_returns_unknown(self, twin):
        result = await twin.predict_preference("music")
        assert result["preference"] == "unknown"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_with_memories_calls_llm(self, twin):
        twin._memory.search.return_value = [
            {"content": "Loves jazz music"},
            {"content": "Listens to Coltrane often"},
        ]
        json_text = '{"preference": "jazz", "confidence": 0.9}'
        twin._llm.chat.return_value = {"choices": [{"message": {"content": json_text, "tool_calls": []}}]}
        twin._llm.extract_response = MagicMock(return_value=(json_text, []))
        result = await twin.predict_preference("music")
        assert result["category"] == "music"
        assert result["preference"] == "jazz"
        assert result["confidence"] == 0.9


class TestDailyReflection:
    @pytest.mark.asyncio
    async def test_no_episodes_returns_default(self, twin):
        result = await twin.daily_reflection()
        assert "Not much happened" in result

    @pytest.mark.asyncio
    async def test_with_episodes_calls_llm(self, twin):
        twin._memory.episode_recent.return_value = [
            {"summary": "Had a productive coding session", "timestamp": time.time()}
        ]
        reflection_text = "Today was great. I shipped a new feature."
        twin._llm.chat.return_value = {"choices": [{"message": {"content": reflection_text, "tool_calls": []}}]}
        twin._llm.extract_response = MagicMock(return_value=(reflection_text, []))
        result = await twin.daily_reflection()
        assert "shipped" in result


class TestHelpers:
    def test_extract_name_from_identity(self):
        assert DigitalTwin._extract_name("You are Alex.") == "Alex"

    def test_extract_name_fallback(self):
        assert DigitalTwin._extract_name("Random text without name line") == "the user"

    def test_extract_name_too_long(self):
        long = "You are " + "A" * 100 + "."
        assert DigitalTwin._extract_name(long) == "the user"

    def test_parse_json_safely_valid(self):
        result = DigitalTwin._parse_json_safely('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_safely_code_fence(self):
        result = DigitalTwin._parse_json_safely('```json\n{"key": "val"}\n```')
        assert result == {"key": "val"}

    def test_parse_json_safely_invalid(self):
        assert DigitalTwin._parse_json_safely("not json at all") == {}

    def test_format_episodes_empty(self):
        assert DigitalTwin._format_episodes([]) == ""

    def test_format_episodes_filters_old(self):
        old = time.time() - (60 * 86_400)
        result = DigitalTwin._format_episodes([{"summary": "old", "timestamp": old}])
        assert result == ""
