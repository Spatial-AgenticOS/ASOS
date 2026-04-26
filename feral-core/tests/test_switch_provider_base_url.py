"""Regression tests for LLMProvider.switch_provider(base_url=...).

The v2026.5.0 release shipped a crash: ``api/routes/config.py::update_config``
passes ``base_url=`` into ``switch_provider`` but the signature did not
accept that kwarg, so every v2 "Save & switch" 500'd with a TypeError.

This module pins:
  * The kwarg is accepted (no TypeError).
  * An explicit override lands on ``self.base_url``.
  * Legacy callers that omit ``base_url`` keep the auto-resolved default.
  * Empty string is treated as "no override" (matches the v2 settings
    route, which passes ``llm_config.get("base_url", "")``).
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from agents.llm_provider import LLMProvider


@pytest.fixture
def provider() -> LLMProvider:
    return LLMProvider()


class TestSignature:
    def test_switch_provider_accepts_base_url_kwarg(self):
        """The v2026.5.0 crash shape: switch_provider(..., base_url='...')."""
        sig = inspect.signature(LLMProvider.switch_provider)
        assert "base_url" in sig.parameters, (
            "switch_provider MUST accept base_url= kwarg; "
            "api/routes/config.py::update_config passes it and a missing "
            "kwarg re-introduces the shipped v2026.5.0 TypeError crash"
        )
        param = sig.parameters["base_url"]
        assert param.default == "", (
            "base_url default MUST be empty string so the legacy "
            "no-arg call path keeps auto-resolving per PROVIDER_BASES"
        )


class TestOverrideLandsOnSelf:
    def test_explicit_override_for_openai(self, provider):
        asyncio.run(provider.switch_provider(
            "openai",
            model="gpt-5.5",
            api_key="test-key-do-not-commit",
            base_url="https://custom-gateway.example.com/v1",
        ))
        assert provider.base_url == "https://custom-gateway.example.com/v1"
        assert provider.model == "gpt-5.5"
        assert provider.provider == "openai"

    def test_explicit_override_for_lmstudio(self, provider):
        asyncio.run(provider.switch_provider(
            "lmstudio",
            model="local-model",
            base_url="http://192.168.1.100:1234/v1",
        ))
        assert provider.base_url == "http://192.168.1.100:1234/v1"

    def test_explicit_override_for_ollama(self, provider):
        asyncio.run(provider.switch_provider(
            "ollama",
            model="llama3.2",
            base_url="http://ollama.lan:11434/v1",
        ))
        assert provider.base_url == "http://ollama.lan:11434/v1"


class TestEmptyStringIsNoOverride:
    """The v2 settings route passes llm_config.get('base_url', '') which
    returns '' when the user hasn't set a custom URL. That empty string
    must be treated as 'use the auto-resolved default', not as 'force
    self.base_url to an empty string'."""

    def test_empty_override_keeps_auto_default_for_openai(self, provider):
        asyncio.run(provider.switch_provider(
            "openai",
            model="gpt-5.5",
            api_key="test-key-do-not-commit",
            base_url="",
        ))
        assert provider.base_url == "https://api.openai.com/v1"

    def test_omitted_override_keeps_auto_default_for_anthropic(self, provider):
        # The legacy no-kwarg call shape.
        asyncio.run(provider.switch_provider(
            "anthropic",
            model="claude-opus-4-7",
            api_key="test-key-do-not-commit",
        ))
        assert provider.base_url == "https://api.anthropic.com/v1"

    def test_empty_override_lmstudio_falls_back_to_default(self, provider):
        asyncio.run(provider.switch_provider(
            "lmstudio",
            model="local-model",
            base_url="",
        ))
        assert provider.base_url == "http://localhost:1234/v1"


class TestConfigRouteShape:
    """Replay the exact call shape from api/routes/config.py:103 (the
    crash site) — if this test passes, the shipped route doesn't
    500."""

    def test_config_route_call_shape_does_not_crash(self, provider):
        # From api/routes/config.py:103:
        #   state.orchestrator.llm.switch_provider(
        #       new_provider, model=new_model,
        #       base_url=new_base, api_key=new_key
        #   )
        # where new_base == llm_config.get("base_url", "").
        asyncio.run(provider.switch_provider(
            "openai",
            model="gpt-5.5",
            base_url="",
            api_key="test-key-do-not-commit",
        ))
        assert provider.provider == "openai"
        assert provider.base_url == "https://api.openai.com/v1"
