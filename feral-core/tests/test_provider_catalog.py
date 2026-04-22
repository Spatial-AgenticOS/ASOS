"""Unit tests for ProviderCatalog — the unified LLM provider + model registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from providers.base import BaseProvider
from providers.catalog import (
    BUILT_IN_DESCRIPTORS,
    CachedModelList,
    ProviderCatalog,
    ProviderDescriptor,
    get_shared_catalog,
    reset_shared_catalog,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def empty_cache(tmp_path) -> Path:
    return tmp_path / "model_catalog.json"


@pytest.fixture
def catalog(empty_cache) -> ProviderCatalog:
    # Clear env so the built-in adapter factory doesn't see production keys.
    with patch.dict("os.environ", {}, clear=False):
        # Belt-and-suspenders: also drop the common API keys individually.
        for key in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
            "GROQ_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
            "TOGETHER_API_KEY", "FIREWORKS_API_KEY", "AWS_ACCESS_KEY_ID",
        ):
            if key in __import__("os").environ:
                del __import__("os").environ[key]
        yield ProviderCatalog(cache_path=empty_cache)


# ----------------------------------------------------------------------
# Descriptor + list shape
# ----------------------------------------------------------------------


class TestDescriptors:
    def test_built_in_descriptors_cover_core_providers(self, catalog):
        ids = {d.provider_id for d in catalog.list_providers()}
        for pid in ("openai", "anthropic", "gemini", "ollama", "groq"):
            assert pid in ids, f"descriptor missing for {pid}"

    def test_list_providers_is_sorted(self, catalog):
        ids = [d.provider_id for d in catalog.list_providers()]
        assert ids == sorted(ids)

    def test_get_descriptor_known(self, catalog):
        d = catalog.get_descriptor("openai")
        assert d is not None
        assert d.display_name == "OpenAI"
        assert d.requires_api_key is True
        assert d.supports_local is False

    def test_get_descriptor_unknown_returns_none(self, catalog):
        assert catalog.get_descriptor("not-real") is None

    def test_ollama_marked_local(self, catalog):
        d = catalog.get_descriptor("ollama")
        assert d is not None
        assert d.supports_local is True
        assert d.requires_api_key is False
        assert "11434" in d.default_base_url


# ----------------------------------------------------------------------
# Alias resolution
# ----------------------------------------------------------------------


class TestAliases:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("openai", "openai"),
            ("OpenAI", "openai"),
            ("open ai", "openai"),
            ("chatgpt", "openai"),
            ("claude", "anthropic"),
            ("anthropic", "anthropic"),
            ("google gemini", "gemini"),
            ("groq", "groq"),
            ("  openrouter  ", "openrouter"),
            ("open router", "openrouter"),
        ],
    )
    def test_resolves_canonical_and_alias(self, catalog, text, expected):
        assert catalog.resolve_alias(text) == expected

    def test_substring_unambiguous_wins(self, catalog):
        # "llama" is a substring of "ollama" and matches no other id.
        assert catalog.resolve_alias("llama") == "ollama"
        # "deepseek" is unambiguous even as substring.
        assert catalog.resolve_alias("seek") == "deepseek"

    def test_empty_input_returns_none(self, catalog):
        assert catalog.resolve_alias("") is None
        assert catalog.resolve_alias("   ") is None

    def test_ambiguous_substring_returns_none(self, catalog):
        # "o" appears in multiple provider ids; must not silently pick one.
        assert catalog.resolve_alias("o") is None


# ----------------------------------------------------------------------
# Caching + live refresh
# ----------------------------------------------------------------------


class FakeAdapter(BaseProvider):
    """Adapter double that returns a configurable model list."""

    provider_id = "openai"
    display_name = "OpenAI"
    _models = ["fallback-model"]

    def __init__(self, models: list[str], *, raises: bool = False) -> None:
        self._live_models = list(models)
        self._raises = raises

    async def chat(self, *a, **kw):  # pragma: no cover - unused here
        raise NotImplementedError

    async def refresh_models(self):
        if self._raises:
            raise RuntimeError("simulated network failure")
        return list(self._live_models)


class TestModelLists:
    @pytest.mark.asyncio
    async def test_first_call_goes_live_and_caches(self, catalog):
        catalog.register_adapter(FakeAdapter(models=["gpt-9", "gpt-9-mini"]))
        result = await catalog.list_models("openai", live=True, force=True)
        assert result.models == ["gpt-9", "gpt-9-mini"]
        assert result.source == "live"
        assert result.last_refresh > 0

    @pytest.mark.asyncio
    async def test_second_call_within_ttl_hits_cache(self, catalog):
        catalog.register_adapter(FakeAdapter(models=["m1"]))
        first = await catalog.list_models("openai", live=True, force=True)
        # Swap the adapter so a live call would return different data.
        catalog.register_adapter(FakeAdapter(models=["m2"]))
        second = await catalog.list_models("openai", live=True, force=False)
        assert second.models == first.models == ["m1"]

    @pytest.mark.asyncio
    async def test_force_true_ignores_cache(self, catalog):
        catalog.register_adapter(FakeAdapter(models=["m1"]))
        await catalog.list_models("openai", force=True)
        catalog.register_adapter(FakeAdapter(models=["m2"]))
        out = await catalog.list_models("openai", force=True)
        assert out.models == ["m2"]

    @pytest.mark.asyncio
    async def test_live_false_returns_cache_without_refresh(self, catalog):
        catalog.register_adapter(FakeAdapter(models=["cached"]))
        await catalog.list_models("openai", live=True, force=True)
        catalog.register_adapter(FakeAdapter(models=["fresh"], raises=True))
        out = await catalog.list_models("openai", live=False)
        assert out.models == ["cached"]

    @pytest.mark.asyncio
    async def test_refresh_failure_falls_back_to_list_models(self, catalog):
        # No prior cache; live call raises. Adapter's _models (fallback
        # list) should be surfaced with source="fallback".
        catalog.register_adapter(FakeAdapter(models=[], raises=True))
        out = await catalog.list_models("openai", force=True)
        assert out.source == "fallback"

    @pytest.mark.asyncio
    async def test_list_models_unknown_provider_raises(self, catalog):
        with pytest.raises(KeyError):
            await catalog.list_models("not-a-provider")


# ----------------------------------------------------------------------
# Probe
# ----------------------------------------------------------------------


class TestProbe:
    @pytest.mark.asyncio
    async def test_probe_reachable_provider(self, catalog):
        catalog.register_adapter(FakeAdapter(models=["ready"]))
        status = await catalog.probe("openai")
        assert status.reachable is True
        assert status.error == ""

    @pytest.mark.asyncio
    async def test_probe_unreachable_reports_error(self, catalog):
        catalog.register_adapter(FakeAdapter(models=[], raises=True))
        status = await catalog.probe("openai")
        assert status.reachable is False

    @pytest.mark.asyncio
    async def test_probe_unknown_provider_honest(self, catalog):
        status = await catalog.probe("ghost")
        assert status.reachable is False
        assert "unknown" in status.error


# ----------------------------------------------------------------------
# Disk cache
# ----------------------------------------------------------------------


class TestDiskCache:
    @pytest.mark.asyncio
    async def test_cache_persists_to_disk(self, catalog, empty_cache):
        catalog.register_adapter(FakeAdapter(models=["persisted"]))
        await catalog.list_models("openai", force=True)
        assert empty_cache.is_file()
        raw = json.loads(empty_cache.read_text())
        assert raw["providers"]["openai"]["models"] == ["persisted"]

    def test_load_from_disk_rehydrates(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({
            "schema_version": 1,
            "providers": {
                "openai": {"models": ["from-disk"], "last_refresh": 99.0, "source": "cache"},
            },
        }))
        catalog = ProviderCatalog(cache_path=cache)
        # Without a live call the cached value is what list_models returns.
        import asyncio as _aio
        out = _aio.run(catalog.list_models("openai", live=False))
        assert out.models == ["from-disk"]

    def test_corrupted_cache_is_ignored(self, tmp_path):
        cache = tmp_path / "bad.json"
        cache.write_text("not json")
        # Must not raise.
        ProviderCatalog(cache_path=cache)


# ----------------------------------------------------------------------
# Configure
# ----------------------------------------------------------------------


class TestConfigure:
    def test_configure_rebinds_api_key(self, catalog):
        catalog.configure("openai", api_key="sk-test")
        adapter = catalog.get_adapter("openai")
        assert adapter is not None
        # The adapter exposes _api_key on the concrete class.
        assert getattr(adapter, "_api_key", None) == "sk-test"

    def test_configure_unknown_provider_raises(self, catalog):
        with pytest.raises(KeyError):
            catalog.configure("not-real", api_key="k")


# ----------------------------------------------------------------------
# Shared singleton
# ----------------------------------------------------------------------


class TestSharedSingleton:
    def test_get_shared_returns_same_instance(self, tmp_path, monkeypatch):
        reset_shared_catalog()
        monkeypatch.setenv("FERAL_HOME", str(tmp_path / ".feral"))
        first = get_shared_catalog()
        second = get_shared_catalog()
        assert first is second
        reset_shared_catalog()
