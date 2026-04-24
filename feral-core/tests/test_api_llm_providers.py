"""Contract tests for /api/llm/providers + /api/llm/config routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from providers.catalog import ProviderCatalog


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def client(tmp_path):
    catalog = ProviderCatalog(cache_path=tmp_path / "cache.json")
    mock_config = MagicMock()
    _store: dict = {"llm": {"provider": "", "model": "", "base_url": ""}, "audio": {}}

    def _get(section, key, default=None):
        return _store.get(section, {}).get(key, default)

    def _update(section, key, value):
        _store.setdefault(section, {})[key] = value

    mock_config.get.side_effect = _get
    mock_config.update_settings.side_effect = _update

    mock_vault = MagicMock()

    mock = MagicMock()
    mock.provider_catalog = catalog
    mock.config = mock_config
    mock.vault = mock_vault
    mock.orchestrator = None

    with patch("api.state.state", mock), patch("api.routes.llm.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), catalog, mock_config, mock_vault, _store


def test_list_providers_returns_all_builtin(client):
    c, catalog, _cfg, _vault, _store = client
    r = c.get("/api/llm/providers")
    assert r.status_code == 200
    body = r.json()
    ids = {p["id"] for p in body["providers"]}
    # Every built-in descriptor must be exposed to the v2 UI — not a
    # hardcoded subset. This protects against regressions where a
    # provider is added to BUILT_IN_DESCRIPTORS but the UI silently
    # ignores it (the whole reason Settings → Providers was skinny).
    required = {
        "openai", "anthropic", "gemini", "groq", "deepseek",
        "openrouter", "together", "fireworks", "bedrock",
        "ollama", "lmstudio",
    }
    missing = required - ids
    assert not missing, f"catalog is missing providers: {missing}"


def test_provider_descriptor_includes_alias_list(client):
    c, _, _, _, _ = client
    r = c.get("/api/llm/providers")
    entries = {p["id"]: p for p in r.json()["providers"]}
    assert "open ai" in entries["openai"]["aliases"]
    assert entries["openai"]["requires_api_key"] is True
    assert entries["ollama"]["supports_local"] is True


def test_get_provider_unknown_404(client):
    c, _, _, _, _ = client
    r = c.get("/api/llm/providers/not-real")
    assert r.status_code == 404


def test_list_provider_models_uses_catalog(client):
    c, catalog, _, _, _ = client
    from providers.catalog import CachedModelList
    import time as _time
    catalog._models["openai"] = CachedModelList(
        models=["gpt-x", "gpt-y"], last_refresh=_time.time(), source="cache",
    )
    r = c.get("/api/llm/providers/openai/models?live=false")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == ["gpt-x", "gpt-y"]
    assert body["source"] == "cache"


def test_list_provider_models_unknown_404(client):
    c, _, _, _, _ = client
    r = c.get("/api/llm/providers/not-real/models")
    assert r.status_code == 404


def test_probe_calls_adapter(client):
    c, catalog, _, _, _ = client
    fake = MagicMock()
    fake.refresh_models = AsyncMock(return_value=["reachable-model"])
    catalog.register_adapter(type("X", (), {"provider_id": "openai",
                                             "refresh_models": fake.refresh_models,
                                             "list_models": lambda self: []})())
    r = c.post("/api/llm/providers/openai/probe")
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is True
    assert body["error"] == ""


def test_probe_unreachable_shape(client):
    c, catalog, _, _, _ = client
    from providers.base import BaseProvider

    class Broken(BaseProvider):
        provider_id = "openai"
        _models: list = []

        async def chat(self, *a, **k):
            raise NotImplementedError

        async def refresh_models(self):
            raise RuntimeError("boom")

    catalog.register_adapter(Broken())
    r = c.post("/api/llm/providers/openai/probe")
    body = r.json()
    assert body["reachable"] is False
    assert "boom" in body["error"]


def test_configure_stores_key_in_vault(client):
    c, catalog, _, vault, _ = client
    r = c.post(
        "/api/llm/providers/openai/configure",
        json={"api_key": "sk-live", "base_url": "https://openai.example"},
    )
    assert r.status_code == 200
    # Commit 1 widened "stored_by" from "setup_wizard" to "settings" — the
    # key routing is now a single pipe used by setup + Settings alike.
    vault.store.assert_called_with("OPENAI_API_KEY", "sk-live", stored_by="settings")
    body = r.json()
    assert body["persisted"]["vault"] is True


def test_configure_unknown_provider_404(client):
    c, _, _, _, _ = client
    r = c.post("/api/llm/providers/fake/configure", json={"api_key": "x"})
    assert r.status_code == 404


def test_get_config_returns_safe_shape(client):
    c, _, cfg, _, _ = client
    cfg.update_settings("llm", "provider", "openai")
    cfg.update_settings("llm", "model", "gpt-4o-mini")
    r = c.get("/api/llm/config")
    body = r.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"
    assert "api_key" not in body  # never return the key


def test_set_config_persists_and_stores_key(client):
    c, _, cfg, vault, store = client
    r = c.post(
        "/api/llm/config",
        json={
            "provider": "open ai",  # fuzzy alias
            "model": "gpt-new-model-not-yet-released",
            "api_key": "sk-new",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-new-model-not-yet-released"
    assert store["llm"]["provider"] == "openai"
    # See note in test_configure_stores_key_in_vault — stored_by unified.
    vault.store.assert_called_with("OPENAI_API_KEY", "sk-new", stored_by="settings")


def test_set_config_rejects_unknown_provider(client):
    c, _, _, _, _ = client
    r = c.post(
        "/api/llm/config",
        json={"provider": "not-real", "model": "x"},
    )
    assert r.status_code == 400


def test_models_endpoint_exposes_warning_field(client):
    """A 401-driven fallback must surface ``warning`` so the v2 picker
    can render a "key rejected" chip instead of silently lying."""
    c, catalog, _, _, _ = client
    from providers.catalog import CachedModelList
    import time as _time

    catalog._models["openai"] = CachedModelList(
        models=["gpt-fallback"],
        last_refresh=_time.time(),
        source="fallback",
        warning="provider rejected the API key (HTTP 401)",
    )
    r = c.get("/api/llm/providers/openai/models?live=false")
    assert r.status_code == 200
    body = r.json()
    assert body["warning"] == "provider rejected the API key (HTTP 401)"
    assert body["source"] == "fallback"


def test_force_refresh_bypasses_cache(client):
    """``?force=true`` (the Refresh button) must do a live fetch even
    when the disk cache is fresh."""
    c, catalog, _, _, _ = client
    from providers.base import BaseProvider
    from providers.catalog import CachedModelList
    import time as _time

    # Warm cache with stale-looking models that a regression-prone code
    # path might erroneously serve.
    catalog._models["openai"] = CachedModelList(
        models=["stale-cached"], last_refresh=_time.time(), source="cache",
    )

    class _LiveAdapter(BaseProvider):
        provider_id = "openai"
        _models: list = []
        refreshed = 0

        async def chat(self, *a, **kw):
            raise NotImplementedError

        async def refresh_models(self):
            type(self).refreshed += 1
            return ["forced-fresh-model"]

    catalog.register_adapter(_LiveAdapter())
    r = c.get("/api/llm/providers/openai/models?force=true")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == ["forced-fresh-model"]
    assert body["source"] == "live"
    assert _LiveAdapter.refreshed == 1


def test_configure_invalidates_cache_so_next_models_call_goes_live(client):
    """After saving a key the next /models call must hit the wire.

    Without invalidation the v2 picker keeps rendering the pre-key
    model list even after the user pasted a working key — that's the
    user-facing bug we're fixing.
    """
    c, catalog, _, _, _ = client
    from providers.base import BaseProvider
    from providers.catalog import CachedModelList
    import time as _time

    catalog._models["openai"] = CachedModelList(
        models=["pre-key-model"], last_refresh=_time.time(), source="cache",
    )

    r = c.post("/api/llm/providers/openai/configure", json={"api_key": "sk-fresh"})
    assert r.status_code == 200
    # configure() must have wiped the warm cache.
    assert "openai" not in catalog._models

    # Re-bind a deterministic adapter so the next call produces a known
    # live result instead of touching the real OpenAI API.
    class _PostKeyAdapter(BaseProvider):
        provider_id = "openai"
        _models: list = []

        async def chat(self, *a, **kw):
            raise NotImplementedError

        async def refresh_models(self):
            return ["post-key-model"]

    catalog.register_adapter(_PostKeyAdapter())
    r = c.get("/api/llm/providers/openai/models?live=true")
    body = r.json()
    assert body["models"] == ["post-key-model"]
    assert body["source"] == "live"


def test_503_when_catalog_missing():
    mock = MagicMock()
    mock.provider_catalog = None
    mock.config = None
    with patch("api.state.state", mock), patch("api.routes.llm.state", mock):
        from api.server import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/api/llm/providers")
        assert r.status_code == 503
