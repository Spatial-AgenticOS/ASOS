"""Tests for perception.scene — SceneAnalyzer multi-provider VLM pipeline."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from perception.scene import SceneAnalyzer, SCENE_ANALYSIS_PROMPT, TEXT_EXTRACTION_PROMPT


@pytest.fixture()
def llm():
    m = MagicMock()
    m.available = True
    m.chat = AsyncMock(return_value={"choices": [{"message": {"content": ""}}]})
    m.extract_response = MagicMock(return_value=("", []))
    return m


@pytest.fixture()
def analyzer(llm, monkeypatch):
    monkeypatch.delenv("FERAL_VLM_PROVIDER", raising=False)
    return SceneAnalyzer(llm=llm)


# ── Init with different VLM providers ────────────────────────────

def test_init_default_uses_shared_llm(analyzer, llm):
    assert analyzer._vlm_client is None
    assert analyzer.available is True


def test_init_ollama_provider(monkeypatch):
    monkeypatch.setenv("FERAL_VLM_PROVIDER", "ollama")
    monkeypatch.setenv("FERAL_VLM_MODEL", "llava")
    with patch("httpx.AsyncClient"):
        sa = SceneAnalyzer()
    assert sa._vlm_client is not None
    assert sa._vlm_client["type"] == "ollama"


# ── Mode-based prompt selection ──────────────────────────────────

def test_select_prompt_general(analyzer):
    prompt = analyzer._select_prompt("general", "node-1", "")
    assert prompt == SCENE_ANALYSIS_PROMPT


def test_select_prompt_ocr(analyzer):
    prompt = analyzer._select_prompt("ocr", "node-1", "")
    assert prompt == TEXT_EXTRACTION_PROMPT


def test_select_prompt_query(analyzer):
    prompt = analyzer._select_prompt("query", "node-1", "What color is the car?")
    assert "What color is the car?" in prompt


def test_select_prompt_tracking_uses_cache(analyzer):
    analyzer._cache["node-1"] = {"scene_description": "A park with dogs."}
    prompt = analyzer._select_prompt("tracking", "node-1", "")
    assert "A park with dogs." in prompt


# ── JSON parsing ─────────────────────────────────────────────────

def test_parse_json_with_fences(analyzer):
    raw = '```json\n{"scene_description": "office"}\n```'
    result = analyzer._parse_json(raw)
    assert result == {"scene_description": "office"}


def test_parse_json_plain(analyzer):
    result = analyzer._parse_json('{"people_count": 3}')
    assert result["people_count"] == 3


def test_parse_json_invalid(analyzer):
    assert analyzer._parse_json("not json at all") is None


# ── Cooldown enforcement ─────────────────────────────────────────

async def test_cooldown_returns_cached(analyzer, llm):
    scene_json = '{"scene_description": "desk with monitor"}'
    llm.extract_response.return_value = (scene_json, [])

    result = await analyzer.analyze_frame("AAAA==", node_id="n1", force=True)
    assert result is not None

    llm.chat.reset_mock()
    cached = await analyzer.analyze_frame("BBBB==", node_id="n1", force=False)
    llm.chat.assert_not_awaited()
    assert cached == result


# ── History tracking ─────────────────────────────────────────────

def test_push_history_respects_max(analyzer):
    for i in range(10):
        analyzer._push_history("n1", {"scene_description": f"scene-{i}"})
    assert len(analyzer.get_history("n1")) == analyzer._max_history


# ── analyze_with_history ─────────────────────────────────────────

async def test_analyze_with_history_multi_frame(analyzer, llm):
    llm.extract_response.return_value = ('{"activity_summary":"walking"}', [])
    frames = [{"data_b64": "AAAA==", "encoding": "jpeg"} for _ in range(3)]
    result = await analyzer.analyze_with_history(frames, node_id="n1")
    assert result == {"activity_summary": "walking"}
