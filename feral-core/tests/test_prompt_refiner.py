"""Phase 2 (audit-r10 overhaul) regression tests — PromptRefiner.

Pins:
  1. `RefinedRequest` wire contract is stable (fields + defaults).
  2. Feature flag `FERAL_PROMPT_REFINER` is honored — off = identity envelope.
  3. Fast-path: control tokens ("mute", "stop") never hit the LLM.
  4. Fast-path: short utterances (<12 chars) never hit the LLM.
  5. LLM-unavailable → fallback envelope. Never raises.
  6. Caller-supplied `device_target_hint` wins when LLM returns None.
  7. Deterministic keyword extraction: "on my Mac" → `device_target=brain`.
  8. Cache hit returns the same envelope (source flipped to `cache`).
  9. LLM happy-path produces a structured `RefinedRequest` from JSON.
 10. Tolerates fenced JSON / leading prose / malformed payloads.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agents.prompt_refiner import (
    RefinedRequest,
    _RefinerCache,
    _device_target_keyword,
    _is_control_token,
    refine,
)


# ───────────────────────── wire contract ──────────────────────────


def test_refined_request_default_envelope():
    """Every field has a safe default so downstream consumers can read
    them unconditionally."""
    r = RefinedRequest()
    assert r.refined_text == ""
    assert r.raw_text == ""
    assert r.intent_class == "unknown"
    assert r.slots == {}
    assert r.device_target is None
    assert r.suggested_skills == []
    assert r.confidence == 0.0
    assert r.source == "fallback"
    assert r.latency_ms == 0


def test_refined_request_rejects_unknown_intent_class():
    with pytest.raises(Exception):  # noqa: PT011 — pydantic ValidationError
        RefinedRequest(intent_class="wat")


# ───────────────────────── fast-path ──────────────────────────


@pytest.mark.parametrize("token", ["mute", "Mute.", "STOP", "yes", "no", " cancel "])
def test_control_tokens_match(token):
    assert _is_control_token(token)


@pytest.mark.parametrize("non_token", ["mute the mic", "stop now please", "yesterday"])
def test_control_tokens_do_not_overmatch(non_token):
    assert not _is_control_token(non_token)


@pytest.mark.asyncio
async def test_fast_path_control_token_skips_llm(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    llm = AsyncMock()
    llm.available = True
    llm.chat = AsyncMock(side_effect=AssertionError("LLM must not be called"))
    r = await refine("mute", llm=llm)
    assert r.intent_class == "control"
    assert r.source == "fast_path"
    assert llm.chat.await_count == 0


@pytest.mark.asyncio
async def test_fast_path_short_text_skips_llm(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    llm = AsyncMock()
    llm.available = True
    llm.chat = AsyncMock(side_effect=AssertionError("LLM must not be called"))
    r = await refine("hi there", llm=llm)
    assert r.source == "fast_path"
    assert r.refined_text == "hi there"


# ───────────────────────── deterministic device_target ──────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("open my Mac browser to youtube", "brain"),
        ("on the Mac, take a screenshot", "brain"),
        ("via the brain, list my files", "brain"),
        ("call mom on my phone", "phone"),
        ("from my iphone, play music", "phone"),
        ("show me what's on my glasses right now", "glasses"),
        ("via the glasses, snap a photo", "glasses"),
        ("just remind me later", None),
    ],
)
def test_device_target_keyword_extraction(text, expected):
    assert _device_target_keyword(text) == expected


# ───────────────────────── feature flag ──────────────────────────


@pytest.mark.asyncio
async def test_feature_flag_off_returns_identity(monkeypatch):
    monkeypatch.delenv("FERAL_PROMPT_REFINER", raising=False)
    llm = AsyncMock()
    llm.available = True
    llm.chat = AsyncMock(side_effect=AssertionError("must not call LLM when flag off"))
    r = await refine("open my Mac browser please", llm=llm, device_target_hint="brain")
    assert r.refined_text == "open my Mac browser please"
    assert r.device_target == "brain"
    assert r.source == "fallback"
    assert llm.chat.await_count == 0


# ───────────────────────── LLM unavailable ──────────────────────────


@pytest.mark.asyncio
async def test_llm_unavailable_returns_fallback_with_keyword_target(monkeypatch):
    """No LLM available → still extract device_target from keywords +
    return identity rewrite. Never raises, never returns None."""
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    r = await refine("open my Mac browser to youtube.com", llm=None)
    assert r.source == "fallback"
    assert r.device_target == "brain"
    assert r.refined_text == "open my Mac browser to youtube.com"


@pytest.mark.asyncio
async def test_llm_unavailable_no_keyword_match_no_device_target(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    r = await refine("could you remind me to drink water more often", llm=None)
    assert r.source == "fallback"
    assert r.device_target is None


# ───────────────────────── caller hint precedence ──────────────────────────


@pytest.mark.asyncio
async def test_caller_hint_wins_when_llm_returns_null(monkeypatch):
    """When the iOS payload set device_target=brain and the LLM doesn't
    override, the result must carry the caller's hint."""
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    llm = _StubLLM(json.dumps({
        "refined_text": "open the browser",
        "intent_class": "device_action",
        "slots": {"app": "browser"},
        "device_target": None,
        "suggested_skills": ["browser"],
        "confidence": 0.7,
    }))
    cache = _RefinerCache()
    r = await refine("open browser please", llm=llm, device_target_hint="brain", cache=cache)
    assert r.device_target == "brain"
    assert r.source == "llm"


# ───────────────────────── happy path ──────────────────────────


@pytest.mark.asyncio
async def test_llm_happy_path_parses_structured_envelope(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    llm = _StubLLM(json.dumps({
        "refined_text": "On macOS host: open Safari and search YouTube for 'AGI lecture'",
        "intent_class": "device_action",
        "slots": {"app": "Safari", "query": "AGI lecture"},
        "device_target": "brain",
        "suggested_skills": ["desktop_control", "browser"],
        "confidence": 0.92,
    }))
    cache = _RefinerCache()
    r = await refine(
        "please open my mac browser and search youtube for AGI lecture",
        llm=llm,
        cache=cache,
    )
    assert r.intent_class == "device_action"
    assert r.device_target == "brain"
    assert "desktop_control" in r.suggested_skills
    assert r.confidence == pytest.approx(0.92)
    assert r.source == "llm"
    assert r.raw_text == "please open my mac browser and search youtube for AGI lecture"


@pytest.mark.asyncio
async def test_llm_returns_fenced_json_still_parses(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    llm = _StubLLM(
        "```json\n"
        + json.dumps({
            "refined_text": "Call Mom via FaceTime on phone",
            "intent_class": "device_action",
            "device_target": "phone",
            "slots": {"contact": "Mom"},
            "suggested_skills": ["phone.call"],
            "confidence": 0.88,
        })
        + "\n```"
    )
    cache = _RefinerCache()
    r = await refine("call mom on facetime please", llm=llm, cache=cache)
    assert r.device_target == "phone"
    assert r.source == "llm"


@pytest.mark.asyncio
async def test_llm_returns_garbage_falls_back(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    llm = _StubLLM("Sure, I'll help you with that!")
    cache = _RefinerCache()
    r = await refine("open my mac browser to youtube", llm=llm, cache=cache)
    assert r.source == "fallback"
    assert r.refined_text == "open my mac browser to youtube"
    # Keyword extraction still fires on fallback path.
    assert r.device_target == "brain"


@pytest.mark.asyncio
async def test_llm_timeout_falls_back(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")

    async def _slow(*_a, **_kw):
        await asyncio.sleep(10)
        return {}

    llm = _SimpleAsyncLLM(_slow)
    cache = _RefinerCache()
    r = await refine("open my mac browser to youtube", llm=llm, cache=cache)
    assert r.source == "fallback"


# ───────────────────────── cache ──────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_reuses_envelope(monkeypatch):
    monkeypatch.setenv("FERAL_PROMPT_REFINER", "1")
    llm = _StubLLM(json.dumps({
        "refined_text": "Cached refinement",
        "intent_class": "chat",
        "device_target": "brain",
        "confidence": 0.6,
    }))
    cache = _RefinerCache()
    text = "remind me about the meeting tomorrow"
    first = await refine(text, llm=llm, cache=cache)
    second = await refine(text, llm=llm, cache=cache)
    assert first.source == "llm"
    assert second.source == "cache"
    assert second.refined_text == first.refined_text
    assert llm.call_count == 1  # second call hit cache


# ───────────────────────── helpers ──────────────────────────


class _StubLLM:
    """Minimal stand-in for `LLMProvider`. Returns a fixed string each
    call so tests can assert deterministic parsing behavior."""

    def __init__(self, response_text: str):
        self.available = True
        self.response_text = response_text
        self.call_count = 0

    async def chat(self, *, messages: list[dict], **kwargs: Any) -> dict:
        self.call_count += 1
        return {
            "choices": [
                {"message": {"role": "assistant", "content": self.response_text}}
            ]
        }


class _SimpleAsyncLLM:
    def __init__(self, fn):
        self.available = True
        self._fn = fn

    async def chat(self, **kwargs):  # noqa: ANN003
        return await self._fn(**kwargs)
