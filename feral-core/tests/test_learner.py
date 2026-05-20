"""Tests for the Self-Learning Agent (Learner)."""

import pytest
import sqlite3
import tempfile
import os

from memory.store import MemoryStore


class FakeLLM:
    """Deterministic LLM stub for testing knowledge extraction."""

    available = True

    def __init__(self, response_text: str = "[]"):
        self._response_text = response_text

    async def chat(self, messages, tools=None, temperature=0.7, max_tokens=1024):
        return {
            "choices": [{"message": {"content": self._response_text, "tool_calls": []}}]
        }

    def extract_response(self, data):
        if "error" in data or not data.get("choices"):
            return data.get("error", "No response"), []
        text = data["choices"][0].get("message", {}).get("content", "")
        return text, []


@pytest.fixture
def memory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    mem = MemoryStore(db_path=path)
    yield mem
    os.unlink(path)


class TestKnowledgeExtraction:
    async def test_extract_triples_from_conversation(self, memory):
        from agents.learner import Learner

        llm = FakeLLM(response_text='[{"subject":"user","predicate":"allergic_to","object":"peanuts"}]')
        learner = Learner(llm=llm, memory=memory)

        memory.working_push("s1", {"role": "user", "text": "I'm allergic to peanuts"})
        memory.working_push("s1", {"role": "assistant", "text": "I'll remember that."})
        memory.working_push("s1", {"role": "user", "text": "Thanks"})

        await learner.extract_knowledge("s1")

        knowledge = await memory.knowledge_query(subject="user", predicate="allergic_to")
        assert len(knowledge) >= 1
        assert knowledge[0]["object"] == "peanuts"

    async def test_no_extraction_from_empty_context(self, memory):
        from agents.learner import Learner

        llm = FakeLLM(response_text='[]')
        learner = Learner(llm=llm, memory=memory)

        await learner.extract_knowledge("empty_session")
        assert await memory.knowledge_query(subject="user") == []

    async def test_extract_skips_non_json(self, memory):
        from agents.learner import Learner

        llm = FakeLLM(response_text="I could not extract any facts.")
        learner = Learner(llm=llm, memory=memory)

        memory.working_push("s1", {"role": "user", "text": "Hello world"})
        memory.working_push("s1", {"role": "user", "text": "How are you?"})

        await learner.extract_knowledge("s1")
        # Should not crash, no knowledge stored
        assert await memory.knowledge_query(subject="user") == []


class TestSessionSummarization:
    async def test_summarize_session(self, memory):
        from agents.learner import Learner

        summary_text = "User asked about weather in NYC. Assistant provided forecast."
        llm = FakeLLM(response_text=summary_text)
        learner = Learner(llm=llm, memory=memory)

        for i in range(5):
            memory.working_push("s2", {"role": "user", "text": f"Message {i}"})

        await learner.summarize_session("s2")

        episodes = await memory.episode_recent(limit=5, session_id="s2")
        summaries = [e for e in episodes if e["event_type"] == "session_summary"]
        assert len(summaries) == 1
        assert "weather" in summaries[0]["summary"].lower()

    async def test_skip_short_sessions(self, memory):
        from agents.learner import Learner

        llm = FakeLLM(response_text="Summary")
        learner = Learner(llm=llm, memory=memory)

        memory.working_push("short", {"role": "user", "text": "Hi"})

        await learner.summarize_session("short")
        episodes = await memory.episode_recent(session_id="short")
        assert len(episodes) == 0


class TestRoutingPenalties:
    async def test_no_penalties_with_no_logs(self, memory):
        from agents.learner import Learner

        llm = FakeLLM()
        learner = Learner(llm=llm, memory=memory)
        penalties = await learner.get_routing_penalties()
        assert penalties == {}

    async def test_penalty_for_failing_skill(self, memory):
        from agents.learner import Learner

        llm = FakeLLM()
        learner = Learner(llm=llm, memory=memory)

        for i in range(10):
            await memory.log_execution(
                session_id="s1", skill_id="broken_api",
                endpoint_id="fetch", args={},
                result_status="failure",
                result_summary="500 error",
            )

        reliability = await learner.get_skill_reliability("broken_api")
        assert reliability["success_rate"] == 0.0
        assert reliability["recommendation"] == "avoid"

        penalties = await learner.get_routing_penalties()
        assert "broken_api" in penalties
        assert penalties["broken_api"] <= 0.2

    async def test_healthy_skill_no_penalty(self, memory):
        from agents.learner import Learner

        llm = FakeLLM()
        learner = Learner(llm=llm, memory=memory)

        for i in range(10):
            await memory.log_execution(
                session_id="s1", skill_id="good_api",
                endpoint_id="fetch", args={},
                result_status="success",
                result_summary="ok",
            )

        reliability = await learner.get_skill_reliability("good_api")
        assert reliability["success_rate"] == 1.0
        assert reliability["recommendation"] == "normal"

        penalties = await learner.get_routing_penalties()
        assert "good_api" not in penalties


class TestMessageInterval:
    async def test_extraction_triggers_at_interval(self, memory):
        from agents.learner import Learner

        llm = FakeLLM(response_text='[{"subject":"user","predicate":"name_is","object":"Alice"}]')
        learner = Learner(llm=llm, memory=memory)
        learner._extract_interval = 3

        # Push working memory so extraction has something to work with
        for i in range(3):
            memory.working_push("s1", {"role": "user", "text": f"My name is Alice {i}"})

        for i in range(3):
            await learner.on_message("s1", "user", f"message {i}")

        knowledge = await memory.knowledge_query(subject="user", predicate="name_is")
        assert len(knowledge) >= 1
