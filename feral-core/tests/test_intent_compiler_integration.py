"""Integration tests for agents/intent_compiler.py — validation, JSON fallback, timezone."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.intent_compiler import IntentCompiler, MicroAction


# ── Helper: mock LLM ────────────────────────────────────────────────────────

def _mock_llm(response_text: str):
    llm = MagicMock()
    llm.chat = AsyncMock(return_value={
        "choices": [{"message": {"content": response_text}}],
    })
    llm.extract_response = MagicMock(return_value=(response_text, []))
    return llm


def _mock_skill_registry(*skill_ids: str):
    reg = MagicMock()
    reg.skills = {sid: MagicMock() for sid in skill_ids}
    return reg


# ── Compile intent with valid actions ────────────────────────────────────────

class TestCompileIntent:
    @pytest.mark.asyncio
    async def test_compile_produces_valid_actions(self):
        actions = [
            {"description": f"Step {i}", "tool": f"spanish.lesson_{i}", "difficulty": 0.3 + i * 0.1}
            for i in range(1, 6)
        ]
        llm = _mock_llm(json.dumps(actions))
        registry = _mock_skill_registry("spanish")
        compiler = IntentCompiler(llm=llm, skill_registry=registry)

        plan = await compiler.compile_intent("learn Spanish")
        assert len(plan.micro_actions) == 5
        for action in plan.micro_actions:
            assert action.tool_hint.startswith("spanish.")
            assert 0 <= action.difficulty <= 1

    @pytest.mark.asyncio
    async def test_actions_reference_registered_skills(self):
        actions = [
            {"description": "vocab drill", "tool": "spanish.vocab", "difficulty": 0.3},
            {"description": "grammar quiz", "tool": "spanish.grammar", "difficulty": 0.5},
        ]
        llm = _mock_llm(json.dumps(actions))
        registry = _mock_skill_registry("spanish")
        compiler = IntentCompiler(llm=llm, skill_registry=registry)

        plan = await compiler.compile_intent("learn Spanish")
        for action in plan.micro_actions:
            skill_id = action.tool_hint.split(".")[0]
            assert skill_id in registry.skills


# ── Validation rejects bad actions ───────────────────────────────────────────

class TestValidation:
    def test_empty_tool_rejected(self):
        compiler = IntentCompiler()
        ok, reason = compiler._validate_action({"tool": ""})
        assert not ok
        assert "empty" in reason

    def test_no_dot_rejected(self):
        compiler = IntentCompiler()
        ok, reason = compiler._validate_action({"tool": "nodot"})
        assert not ok
        assert "skill.endpoint" in reason

    def test_manual_accepted(self):
        compiler = IntentCompiler()
        ok, _ = compiler._validate_action({"tool": "manual"})
        assert ok

    def test_unknown_skill_rejected(self):
        registry = _mock_skill_registry("known_skill")
        compiler = IntentCompiler(skill_registry=registry)
        ok, reason = compiler._validate_action({"tool": "unknown.endpoint"}, registry)
        assert not ok
        assert "unknown skill" in reason

    def test_known_skill_accepted(self):
        registry = _mock_skill_registry("known_skill")
        compiler = IntentCompiler(skill_registry=registry)
        ok, _ = compiler._validate_action({"tool": "known_skill.do_thing"}, registry)
        assert ok

    @pytest.mark.asyncio
    async def test_invalid_actions_recorded_in_rejected(self):
        actions = [
            {"description": "good", "tool": "lang.vocab", "difficulty": 0.3},
            {"description": "bad", "tool": "nope", "difficulty": 0.5},
        ]
        llm = _mock_llm(json.dumps(actions))
        registry = _mock_skill_registry("lang")
        compiler = IntentCompiler(llm=llm, skill_registry=registry)
        await compiler.compile_intent("test")
        assert len(compiler._rejected_actions) == 1
        assert "nope" in str(compiler._rejected_actions[0])


# ── JSON parse fallback ──────────────────────────────────────────────────────

class TestJSONFallback:
    @pytest.mark.asyncio
    async def test_malformed_json_produces_single_action(self):
        llm = _mock_llm("this is not valid JSON at all {{{")
        compiler = IntentCompiler(llm=llm)

        plan = await compiler.compile_intent("do something")
        assert len(plan.micro_actions) == 1
        assert plan.micro_actions[0].tool_hint == "manual"
        assert plan.micro_actions[0].description == "do something"


# ── Timezone-aware today actions ─────────────────────────────────────────────

class TestTodayTimezone:
    def test_uses_configured_timezone(self):
        compiler = IntentCompiler(user_timezone="America/New_York")
        compiler._plans["p1"] = MagicMock(
            plan_id="p1", intent="test", status="active", progress=0.0,
            micro_actions=[MicroAction(description="task", tool_hint="manual")],
        )
        actions = compiler.get_today_actions()
        assert len(actions) >= 1

    def test_explicit_tz_override(self):
        compiler = IntentCompiler(user_timezone="UTC")
        compiler._plans["p1"] = MagicMock(
            plan_id="p1", intent="test", status="active", progress=0.0,
            micro_actions=[MicroAction(description="task", tool_hint="manual")],
        )
        actions = compiler.get_today_actions(tz_name="Asia/Tokyo")
        assert len(actions) >= 1

    def test_scheduled_past_date_excluded(self):
        compiler = IntentCompiler(user_timezone="UTC")
        compiler._plans["p1"] = MagicMock(
            plan_id="p1", intent="test", status="active", progress=0.0,
            micro_actions=[MicroAction(
                description="old task", tool_hint="manual",
                scheduled_time="2020-01-01T10:00:00",
            )],
        )
        actions = compiler.get_today_actions()
        assert len(actions) == 0
