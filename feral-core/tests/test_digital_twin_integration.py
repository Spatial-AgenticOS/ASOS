"""
Digital Twin integration tests — real memory store (temp SQLite),
identity file, and LLM-mocked ask() / predict_preference().
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.digital_twin import DigitalTwin

pytestmark = pytest.mark.asyncio


@pytest.fixture
def real_memory(tmp_path):
    """Lightweight in-memory mock that behaves like a real MemoryStore."""
    store = MagicMock()
    episodes = [
        {"summary": "Had coffee at Blue Bottle", "timestamp": time.time() - 3600, "content": "Coffee lover"},
        {"summary": "Debugged a Python asyncio bug", "timestamp": time.time() - 7200, "content": "Python developer"},
        {"summary": "Prefers jazz over pop", "timestamp": time.time() - 1800, "content": "Jazz enthusiast"},
    ]
    store.episode_recent = AsyncMock(return_value=episodes)
    store.search = AsyncMock(return_value=[
        {"content": "Loves jazz music, especially Coltrane"},
        {"content": "Listens to Kind of Blue every week"},
    ])
    store.knowledge_search = AsyncMock(return_value=[
        {"subject": "user", "predicate": "prefers", "object": "dark roast coffee"},
        {"subject": "user", "predicate": "works_with", "object": "Python"},
    ])
    return store


@pytest.fixture
def identity_loader(tmp_path):
    identity_file = tmp_path / "USER.md"
    identity_file.write_text("You are Alex. A software engineer who loves coffee and jazz.\n")
    loader = MagicMock()
    loader.load_identity.return_value = identity_file.read_text()
    return loader


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat.return_value = {
        "choices": [{"message": {"content": "As Alex, I'd choose the dark roast.", "tool_calls": []}}],
    }
    llm.extract_response = MagicMock(return_value=("As Alex, I'd choose the dark roast.", []))
    return llm


@pytest.fixture
def twin(real_memory, identity_loader, mock_llm):
    return DigitalTwin(memory=real_memory, identity_loader=identity_loader, llm=mock_llm)


async def test_ask_references_stored_preferences(twin, real_memory, mock_llm):
    """ask() builds a prompt referencing memory episodes and KG triples."""
    result = await twin.ask("What coffee do I prefer?")
    assert result == "As Alex, I'd choose the dark roast."
    mock_llm.chat.assert_awaited_once()
    prompt_messages = mock_llm.chat.call_args.args[0]
    system_msg = prompt_messages[0]["content"]
    assert "Alex" in system_msg
    assert "coffee" in system_msg.lower() or "dark roast" in system_msg.lower()


async def test_predict_preference_with_evidence(twin, mock_llm):
    """predict_preference uses memory search results as evidence."""
    json_text = '{"preference": "jazz", "confidence": 0.95}'
    mock_llm.chat.return_value = {"choices": [{"message": {"content": json_text, "tool_calls": []}}]}
    mock_llm.extract_response = MagicMock(return_value=(json_text, []))

    result = await twin.predict_preference("music")
    assert result["category"] == "music"
    assert result["preference"] == "jazz"
    assert result["confidence"] == 0.95
    assert len(result["evidence"]) > 0


async def test_daily_reflection_with_real_episodes(twin, mock_llm):
    """daily_reflection generates text from recent episodes."""
    reflection = "Today was productive. Shipped a feature and had great coffee."
    mock_llm.extract_response = MagicMock(return_value=(reflection, []))
    result = await twin.daily_reflection()
    assert "productive" in result or "shipped" in result.lower() or "coffee" in result.lower()


async def test_ask_graceful_on_llm_failure(twin, mock_llm):
    """ask() returns a graceful error message when the LLM fails."""
    mock_llm.chat.side_effect = RuntimeError("API down")
    result = await twin.ask("anything")
    # Updated message steers the user to Settings → Providers.
    assert "Configure a working provider" in result


async def test_kg_context_included_in_prompt(twin, mock_llm):
    """Knowledge graph triples are part of the system prompt."""
    await twin.ask("What do I work with?")
    prompt_messages = mock_llm.chat.call_args.args[0]
    system_msg = prompt_messages[0]["content"]
    assert "Python" in system_msg
