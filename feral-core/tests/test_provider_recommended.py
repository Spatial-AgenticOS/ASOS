"""Tests for the per-provider "recommended" (latest-relevant) overlay.

The conductor-curated shortlist is the second filter that follows the
model-class classifier. First ``classify()`` drops non-chat classes,
then ``is_recommended()`` keeps only the 2026-04-26 picks per provider.
The v2 Settings picker defaults to ``recommended=True`` so the user
sees a clean 6-10 model shortlist per provider instead of all 132
(OpenAI) or all 355 (OpenRouter) raw ids.
"""

from __future__ import annotations

import pytest

from providers.recommended import is_recommended, recommended_for


class TestOpenAIShortlist:
    def test_flagship_is_recommended(self):
        for m in ("gpt-5.5", "gpt-5.5-pro", "gpt-5.4", "gpt-5.4-mini", "gpt-5"):
            assert is_recommended("openai", m), m

    def test_reasoning_tier_is_recommended(self):
        for m in ("o3", "o3-mini", "o4-mini"):
            assert is_recommended("openai", m), m

    def test_legacy_chat_is_NOT_recommended(self):
        for m in (
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-0125",
            "gpt-3.5-turbo-instruct",
            "gpt-4",
            "gpt-4-0613",
            "gpt-4-turbo",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4o-2024-05-13",
            "davinci-002",
            "babbage-002",
        ):
            assert not is_recommended("openai", m), m

    def test_non_chat_is_NOT_recommended(self):
        for m in (
            "text-embedding-3-small",
            "text-embedding-3-large",
            "whisper-1",
            "dall-e-3",
            "gpt-4o-audio-preview",
            "tts-1",
            "chatgpt-image-latest",
        ):
            assert not is_recommended("openai", m), m


class TestAnthropicShortlist:
    def test_current_generation_is_recommended(self):
        for m in (
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "claude-haiku-4-5-20251001",
        ):
            assert is_recommended("anthropic", m), m

    def test_older_dated_variants_NOT_recommended(self):
        for m in (
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-opus-4-1-20250805",
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-5-20251101",
        ):
            assert not is_recommended("anthropic", m), m


class TestDeepSeekShortlist:
    def test_v4_family_is_recommended(self):
        assert is_recommended("deepseek", "deepseek-v4-pro")
        assert is_recommended("deepseek", "deepseek-v4-flash")

    def test_deprecated_aliases_NOT_recommended(self):
        # Upstream deprecates 2026-07-24.
        for m in ("deepseek-chat", "deepseek-reasoner"):
            assert not is_recommended("deepseek", m), m


class TestGeminiShortlist:
    def test_3x_tier_is_recommended(self):
        for m in (
            "gemini-3.1-pro-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-preview",
            "gemini-3-flash-preview",
        ):
            assert is_recommended("gemini", m), m

    def test_25_stable_still_recommended(self):
        for m in ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"):
            assert is_recommended("gemini", m), m

    def test_rolling_aliases_recommended(self):
        for m in ("gemini-pro-latest", "gemini-flash-latest", "gemini-flash-lite-latest"):
            assert is_recommended("gemini", m), m

    def test_non_chat_NOT_recommended(self):
        for m in (
            "gemini-embedding-001",
            "imagen-4.0-generate-001",
            "veo-3.0-generate-001",
            "gemma-3-27b-it",
            "lyria-3-pro-preview",
            "aqa",
        ):
            assert not is_recommended("gemini", m), m

    def test_20_tier_NOT_recommended(self):
        # 2.0 is widely deployed but not the conductor pick for new
        # users — 2.5 / 3.x / latest aliases cover every need.
        for m in ("gemini-2.0-flash", "gemini-2.0-flash-lite"):
            assert not is_recommended("gemini", m), m


class TestGroqShortlist:
    def test_llama_4_and_3_3_recommended(self):
        assert is_recommended("groq", "llama-3.3-70b-versatile")
        assert is_recommended("groq", "llama-3.1-8b-instant")
        assert is_recommended(
            "groq", "meta-llama/llama-4-scout-17b-16e-instruct"
        )

    def test_non_chat_NOT_recommended(self):
        for m in (
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "canopylabs/orpheus-v1-english",
            "meta-llama/llama-prompt-guard-2-22m",
        ):
            assert not is_recommended("groq", m), m


class TestOpenRouterPrefixMatch:
    def test_major_provider_routes_recommended(self):
        for m in (
            "anthropic/claude-opus-4-7",
            "openai/gpt-5.5",
            "google/gemini-3-pro",
            "meta-llama/llama-4-scout",
            "deepseek/deepseek-v4-pro",
            "x-ai/grok-3",
            "mistralai/mixtral-8x7b",
            "qwen/qwen3-32b",
        ):
            assert is_recommended("openrouter", m), m

    def test_long_tail_NOT_recommended(self):
        for m in (
            "aion-labs/aion-2.0",
            "alpindale/goliath-120b",
            "anthracite-org/magnum-v4-72b",
            "alfredpros/codellama-7b-instruct-solidity",
            "allenai/olmo-3-32b-think",
        ):
            assert not is_recommended("openrouter", m), m


class TestLocalBackends:
    def test_lmstudio_always_recommended(self):
        # Local inventory is the authoritative list.
        assert is_recommended("lmstudio", "any-model-the-user-loaded")
        assert is_recommended("ollama", "llama3:latest")
        assert is_recommended("local", "whatever")

    def test_unknown_provider_permissive(self):
        assert is_recommended("brand-new-provider", "some-model")


class TestRecommendedFor:
    def test_filter_preserves_order(self):
        full = [
            "gpt-3.5-turbo",  # legacy — drops
            "gpt-5.5",        # keeps
            "gpt-4o",         # legacy — drops
            "gpt-5.4-mini",   # keeps
            "babbage-002",    # non-chat — drops
            "o3",             # keeps
        ]
        assert recommended_for("openai", full) == ["gpt-5.5", "gpt-5.4-mini", "o3"]

    def test_empty_list_empty_result(self):
        assert recommended_for("openai", []) == []

    def test_empty_model_id_filtered(self):
        assert not is_recommended("openai", "")
