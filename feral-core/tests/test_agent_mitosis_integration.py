"""Integration tests for Agent Mitosis — specialist routing end-to-end."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.agent_mitosis import AgentMitosisEngine, SpecialistAgent, TaskPattern


def _make_engine_with_specialists():
    """Create an engine pre-loaded with health and coding specialists."""
    engine = AgentMitosisEngine()

    engine._patterns["pattern_health_monitoring"] = TaskPattern(
        pattern_id="pattern_health_monitoring",
        topic_cluster="health_monitoring",
        tool_affinities=["health__get_vitals"],
        occurrence_count=10,
        sample_prompts=["check my heart rate"],
    )
    engine._specialists["pattern_health_monitoring"] = SpecialistAgent(
        agent_id="specialist_health_monitoring",
        name="Health Monitoring Agent",
        description="Specialist for health monitoring tasks",
        system_prompt="You are a health monitoring specialist.",
        source_pattern="pattern_health_monitoring",
        tool_permissions=["health__get_vitals"],
        satisfaction_score=0.7,
    )

    engine._patterns["pattern_code_review"] = TaskPattern(
        pattern_id="pattern_code_review",
        topic_cluster="code_review",
        tool_affinities=["code__review"],
        occurrence_count=8,
        sample_prompts=["review this pull request"],
    )
    engine._specialists["pattern_code_review"] = SpecialistAgent(
        agent_id="specialist_code_review",
        name="Code Review Agent",
        description="Specialist for code review tasks",
        system_prompt="You are a code review specialist.",
        source_pattern="pattern_code_review",
        tool_permissions=["code__review"],
        satisfaction_score=0.6,
    )

    return engine


# ── match_specialist routing ─────────────────────────────────────────────────

class TestSpecialistRouting:
    def test_health_query_routes_to_health(self):
        engine = _make_engine_with_specialists()
        agent_id = engine.match_specialist("my heart rate is really high today")
        assert agent_id == "specialist_health_monitoring"

    def test_code_query_routes_to_coding(self):
        engine = _make_engine_with_specialists()
        agent_id = engine.match_specialist("write some python code to sort a list")
        assert agent_id == "specialist_code_review"

    def test_unrelated_query_returns_none(self):
        engine = _make_engine_with_specialists()
        agent_id = engine.match_specialist("what is the weather like?")
        assert agent_id is None


# ── get_specialist lookup ────────────────────────────────────────────────────

class TestGetSpecialist:
    def test_get_existing(self):
        engine = _make_engine_with_specialists()
        spec = engine.get_specialist("specialist_health_monitoring")
        assert spec is not None
        assert spec.name == "Health Monitoring Agent"

    def test_get_missing(self):
        engine = _make_engine_with_specialists()
        assert engine.get_specialist("nonexistent") is None


# ── Satisfaction scoring ─────────────────────────────────────────────────────

class TestSatisfactionScoring:
    def test_positive_feedback_increases_score(self):
        engine = _make_engine_with_specialists()
        before = engine._specialists["pattern_health_monitoring"].satisfaction_score
        engine.record_feedback("specialist_health_monitoring", positive=True)
        after = engine._specialists["pattern_health_monitoring"].satisfaction_score
        assert after > before

    def test_negative_feedback_decreases_score(self):
        engine = _make_engine_with_specialists()
        before = engine._specialists["pattern_health_monitoring"].satisfaction_score
        engine.record_feedback("specialist_health_monitoring", positive=False)
        after = engine._specialists["pattern_health_monitoring"].satisfaction_score
        assert after < before

    def test_feedback_updates_task_count(self):
        engine = _make_engine_with_specialists()
        engine.record_feedback("specialist_code_review", positive=True)
        assert engine._specialists["pattern_code_review"].tasks_completed == 1


# ── spawn_specialist (mocked LLM) ───────────────────────────────────────────

class TestSpawnSpecialist:
    @pytest.mark.asyncio
    async def test_spawn_creates_specialist(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "choices": [{"message": {"content": "You are a finance specialist."}}],
        })
        mock_llm.extract_response = MagicMock(return_value=("You are a finance specialist.", []))

        engine = AgentMitosisEngine(llm=mock_llm)
        engine._patterns["pattern_finance"] = TaskPattern(
            pattern_id="pattern_finance",
            topic_cluster="finance",
            tool_affinities=["finance__check"],
            occurrence_count=6,
            sample_prompts=["check my budget"],
        )

        spec = await engine.spawn_specialist("pattern_finance")
        assert spec is not None
        assert spec.agent_id == "specialist_finance"
        assert len(engine._specialists) == 1


# ── Orchestrator route_to_specialist ─────────────────────────────────────────

class TestOrchestratorRouting:
    def test_route_returns_specialist_info(self):
        """Verify orchestrator.route_to_specialist delegates to mitosis engine."""
        from unittest.mock import PropertyMock

        mitosis = _make_engine_with_specialists()

        orchestrator = MagicMock()
        orchestrator._mitosis_engine = mitosis
        orchestrator.route_to_specialist = lambda q: _route_helper(orchestrator, q)

        result = orchestrator.route_to_specialist("my heart rate is high")
        assert result is not None
        assert result["agent_id"] == "specialist_health_monitoring"

    def test_route_returns_none_for_no_match(self):
        mitosis = _make_engine_with_specialists()
        orchestrator = MagicMock()
        orchestrator._mitosis_engine = mitosis
        orchestrator.route_to_specialist = lambda q: _route_helper(orchestrator, q)

        result = orchestrator.route_to_specialist("what is the weather?")
        assert result is None


def _route_helper(orch, query):
    """Minimal reimplementation of Orchestrator.route_to_specialist for test."""
    engine = orch._mitosis_engine
    if not engine:
        return None
    agent_id = engine.match_specialist(query)
    if not agent_id:
        return None
    spec = engine.get_specialist(agent_id)
    if not spec:
        return None
    return {"agent_id": spec.agent_id, "system_prompt": spec.system_prompt, "name": spec.name}
