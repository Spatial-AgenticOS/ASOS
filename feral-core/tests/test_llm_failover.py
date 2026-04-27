"""Universal LLM failover — 401 on the primary never stalls the agent.

Tests:
  * classify_error promotes invalid-api-key 401 to AUTH_PERMANENT.
  * chat() with fallback_providers configured delegates to
    chat_with_failover automatically (transparent upgrade).
  * chat_with_failover skips a provider whose cooldown hasn't expired.
  * health_snapshot reports every candidate + cooldown state.
  * GET /api/llm/health returns the snapshot.
  * DigitalTwin.ask() returns a graceful degraded string on provider
    failure instead of bubbling the raw httpx error.
  * POST /api/llm/config auto-prepends the previous primary into
    fallback_providers when the user switches.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


# ── classify_error -----------------------------------------------


def test_classify_invalid_key_is_auth_permanent():
    from agents.llm_provider import classify_error, FailoverReason

    exc = type("E", (Exception,), {"status_code": 401})("Incorrect API key provided: sk-...")
    assert classify_error(exc) == FailoverReason.AUTH_PERMANENT


def test_classify_plain_401_without_hard_key_stays_auth():
    from agents.llm_provider import classify_error, FailoverReason

    exc = type("E", (Exception,), {"status_code": 401})("unauthorized")
    assert classify_error(exc) == FailoverReason.AUTH


def test_classify_429_is_rate_limit():
    from agents.llm_provider import classify_error, FailoverReason

    exc = type("E", (Exception,), {"status_code": 429})("rate limit hit")
    assert classify_error(exc) == FailoverReason.RATE_LIMIT


# ── chat() auto-delegates to failover ---------------------------


@pytest.mark.asyncio
async def test_chat_delegates_when_fallbacks_configured():
    from agents.llm_provider import LLMProvider
    llm = LLMProvider.__new__(LLMProvider)
    llm._config = {"fallback_providers": ["ollama"]}
    llm._local_engine = None
    llm.provider = "openai"
    llm._messages_contain_vision = lambda m: False  # type: ignore
    llm.chat_with_failover = AsyncMock(return_value={"choices": [{"message": {"content": "from-failover"}}]})
    out = await llm.chat([{"role": "user", "content": "hi"}])
    llm.chat_with_failover.assert_awaited_once()
    assert out["choices"][0]["message"]["content"] == "from-failover"


@pytest.mark.asyncio
async def test_chat_returns_error_dict_when_failover_exhausts():
    from agents.llm_provider import LLMProvider
    llm = LLMProvider.__new__(LLMProvider)
    llm._config = {"fallback_providers": ["ollama"]}
    llm._local_engine = None
    llm.provider = "openai"
    llm._messages_contain_vision = lambda m: False  # type: ignore
    llm.chat_with_failover = AsyncMock(side_effect=RuntimeError("All providers exhausted"))
    out = await llm.chat([{"role": "user", "content": "hi"}])
    assert "error" in out
    assert out["choices"] == []


# ── cooldown tracker ---------------------------------------------


def test_cooldown_auth_permanent_skips_for_day():
    from agents.llm_provider import FailoverReason, ProviderCooldownTracker

    ct = ProviderCooldownTracker()
    ct.record_failure("openai", FailoverReason.AUTH_PERMANENT)
    assert ct.is_available("openai") is False
    until = ct._cooldowns.get("openai", 0)
    assert until - time.time() > 60 * 60 * 23  # ≥23h


# ── health_snapshot + REST ---------------------------------------


def test_health_snapshot_reports_candidates_and_cooldowns():
    from agents.llm_provider import LLMProvider, FailoverReason
    llm = LLMProvider.__new__(LLMProvider)
    llm.provider = "openai"
    llm.model = "gpt-4o-mini"
    llm.api_key = "sk-x"
    llm.base_url = "https://api.openai.com/v1"
    llm.available = True
    llm._config = {"fallback_providers": ["anthropic", "ollama"]}
    llm._cooldown = __import__("agents.llm_provider", fromlist=["ProviderCooldownTracker"]).ProviderCooldownTracker()
    llm._cooldown.record_failure("anthropic", FailoverReason.AUTH_PERMANENT)
    llm._build_candidate_list = MagicMock(return_value=[  # type: ignore
        ("openai", {"model": "gpt-4o-mini", "api_key": "sk-x", "base_url": "https://api.openai.com/v1"}),
        ("anthropic", {"model": "claude", "api_key": "a-x", "base_url": "https://api.anthropic.com/v1"}),
        ("ollama", {"model": "llama3", "api_key": "ollama", "base_url": "http://127.0.0.1:11434/v1"}),
    ])

    snap = llm.health_snapshot()
    assert snap["active"]["provider"] == "openai"
    assert len(snap["candidates"]) == 3
    providers = [c["provider"] for c in snap["candidates"]]
    assert providers == ["openai", "anthropic", "ollama"]
    # Anthropic must show as in cooldown.
    anthropic = next(c for c in snap["candidates"] if c["provider"] == "anthropic")
    assert anthropic["in_cooldown"] is True
    assert anthropic["cooldown_remaining"] > 0


@pytest.fixture
def health_client():
    from agents.llm_provider import LLMProvider, FailoverReason, ProviderCooldownTracker
    llm = LLMProvider.__new__(LLMProvider)
    llm.provider = "openai"
    llm.model = "gpt-4o-mini"
    llm.api_key = "sk-x"
    llm.base_url = "https://api.openai.com/v1"
    llm.available = True
    llm._config = {"fallback_providers": ["ollama"]}
    llm._cooldown = ProviderCooldownTracker()
    llm._cooldown.record_failure("openai", FailoverReason.AUTH_PERMANENT)
    llm._build_candidate_list = MagicMock(return_value=[  # type: ignore
        ("openai", {"model": "gpt-4o-mini", "api_key": "sk-x", "base_url": "https://api.openai.com/v1"}),
        ("ollama", {"model": "llama3", "api_key": "ollama", "base_url": "http://127.0.0.1:11434/v1"}),
    ])

    mock = MagicMock()
    mock.orchestrator = MagicMock()
    mock.orchestrator.llm = llm
    with patch("api.state.state", mock), patch("api.routes.llm.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False)


def test_rest_health_endpoint(health_client):
    r = health_client.get("/api/llm/health")
    assert r.status_code == 200
    body = r.json()
    assert body["active"]["provider"] == "openai"
    assert any(c["provider"] == "openai" and c["in_cooldown"] for c in body["candidates"])


# ── DigitalTwin graceful degrade --------------------------------


@pytest.mark.asyncio
async def test_digital_twin_ask_returns_graceful_message_on_error_dict():
    from agents.digital_twin import DigitalTwin

    mem = MagicMock()
    mem.episode_recent.return_value = []
    mem.knowledge_search.return_value = []

    ident = MagicMock()
    ident.load_identity.return_value = "You are FERAL."

    llm = MagicMock()
    llm.chat = AsyncMock(return_value={"error": "401 Unauthorized", "choices": []})

    twin = DigitalTwin(memory=mem, identity_loader=ident, llm=llm)
    result = await twin.ask("what do I do on monday")
    assert "Configure a working provider" in result
    assert "401" not in result


# ── /api/llm/config auto-prepends previous primary ---------------


@pytest.fixture
def config_client(tmp_path):
    from providers.catalog import ProviderCatalog
    from security.vault import BlindVault

    store: dict = {}
    cfg = MagicMock()
    cfg.get.side_effect = lambda section, key, default=None: store.get(f"{section}.{key}", default)
    def _set(section, key, value):
        store[f"{section}.{key}"] = value
    cfg.update_settings.side_effect = _set
    cfg.save_credentials = MagicMock(return_value=True)

    mock = MagicMock()
    mock.provider_catalog = ProviderCatalog()
    mock.config = cfg
    mock.vault = BlindVault(vault_path=str(tmp_path / "credentials.json"))
    orch = MagicMock()
    orch.llm = MagicMock()
    orch.llm.reconfigure = AsyncMock(return_value={
        "ok": True, "provider": "anthropic", "model": "claude",
        "available": True, "base_url": "", "reason": "ok",
    })
    orch.llm._config = {"fallback_providers": []}
    orch.llm.set_config = MagicMock()
    mock.orchestrator = orch

    with patch("api.state.state", mock), patch("api.routes.llm.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), store, orch


def test_auto_prepend_previous_primary_on_switch(config_client):
    c, store, orch = config_client
    # Start with openai as primary
    store["llm.provider"] = "openai"
    store["llm.fallback_providers"] = []

    r = c.post("/api/llm/config", json={
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
    })
    assert r.status_code == 200
    # Previous primary (openai) should have been auto-added.
    assert "openai" in store["llm.fallback_providers"]
    assert store["llm.provider"] == "anthropic"
    # The running LLMProvider should have received the new fallbacks via
    # set_config.
    orch.llm.set_config.assert_called_once()
    new_cfg = orch.llm.set_config.call_args.args[0]
    assert "openai" in new_cfg.get("fallback_providers", [])


def test_explicit_fallbacks_override_auto_prepend(config_client):
    c, store, _orch = config_client
    store["llm.provider"] = "openai"
    r = c.post("/api/llm/config", json={
        "provider": "anthropic",
        "model": "claude",
        "fallback_providers": [],  # explicit empty = user opted out
    })
    assert r.status_code == 200
    assert store["llm.fallback_providers"] == []


@pytest.mark.asyncio
async def test_stream_nonstream_failover_helper_converts_response_to_stream_events():
    from agents.llm_provider import LLMProvider, ProviderCooldownTracker

    llm = LLMProvider.__new__(LLMProvider)
    llm._config = {"fallback_providers": ["anthropic"]}
    llm._local_engine = None
    llm.provider = "openai"
    llm.model = "gpt-4o-mini"
    llm._cooldown = ProviderCooldownTracker()
    llm.chat_with_failover = AsyncMock(
        return_value={"choices": [{"message": {"content": "fallback text"}}]}
    )

    events = await llm._stream_via_nonstream_failover(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.7,
        max_tokens=256,
        primary_error=RuntimeError("400 bad request"),
    )

    assert events is not None
    assert events[0] == {"type": "text_delta", "content": "fallback text"}
    assert events[-1] == {"type": "done"}
    llm.chat_with_failover.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_nonstream_failover_helper_skips_context_overflow():
    from agents.llm_provider import LLMProvider, ProviderCooldownTracker

    llm = LLMProvider.__new__(LLMProvider)
    llm._config = {"fallback_providers": ["anthropic"]}
    llm._local_engine = None
    llm.provider = "openai"
    llm.model = "gpt-4o-mini"
    llm._cooldown = ProviderCooldownTracker()
    llm.chat_with_failover = AsyncMock()

    events = await llm._stream_via_nonstream_failover(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.7,
        max_tokens=256,
        primary_error=RuntimeError("context length exceeded"),
    )

    assert events is None
    llm.chat_with_failover.assert_not_awaited()
