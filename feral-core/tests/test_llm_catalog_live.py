"""Live-fetch / cache-freshness tests for ProviderCatalog.

These pin the contract introduced in 2026.4.29:

* The model picker MUST do a real HTTP fetch when ``live=True``, not
  return the seeded ``_models`` constant.
* A 401 from the upstream MUST fall back to the adapter list AND
  surface a human-readable warning on the response so the v2 picker
  can render a "key rejected" chip.
* The disk cache MUST honour the 6-hour TTL: a 7-hour-old row triggers
  a refetch.
* :meth:`ProviderCatalog.configure` MUST invalidate the cached model
  list so the very next ``list_models`` call goes live with the freshly
  pasted credentials.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from providers.base import BaseProvider
from providers.catalog import (
    DEFAULT_CACHE_TTL_SECONDS,
    CachedModelList,
    ProviderCatalog,
)
from providers.openai_provider import OpenAIProvider


# ----------------------------------------------------------------------
# httpx-level fakes — exercise the real adapter so we know the
# /v1/models call is actually wired up. A regression where the adapter
# stops calling httpx and quietly returns _models would otherwise pass.
# ----------------------------------------------------------------------


def _httpx_response(status_code: int, json_payload: Any) -> httpx.Response:
    request = httpx.Request("GET", "https://api.openai.com/v1/models")
    return httpx.Response(status_code, json=json_payload, request=request)


class _FakeAsyncClient:
    """Drop-in replacement for ``httpx.AsyncClient`` used as a context manager."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.calls: list[str] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, headers: Any = None) -> httpx.Response:  # noqa: D401
        self.calls.append(url)
        return self._response


@pytest.fixture
def catalog(tmp_path):
    cache = tmp_path / "model_catalog.json"
    return ProviderCatalog(cache_path=cache)


# ----------------------------------------------------------------------
# Live fetch — happy path
# ----------------------------------------------------------------------


class TestLiveFetchReturnsResponseModels:
    @pytest.mark.asyncio
    async def test_live_true_uses_response_models_not_hardcoded(self, catalog):
        """``live=True`` returns whatever upstream sent, not ``_models``.

        Pin: if upstream lists 50 models we must surface 50 models; if a
        future regression caused the adapter to fall back to its seeded
        constant the dropdown would silently shrink.
        """
        upstream_models = [
            "gpt-5.5",
            "gpt-5.5-mini",
            "gpt-5.5-nano",
            "o4",
            "o4-mini",
        ]
        # Build the OpenAI adapter directly so we exercise the real
        # refresh_models() code path inside the fix.
        adapter = OpenAIProvider(api_key="sk-test")
        catalog.register_adapter(adapter)

        fake_response = _httpx_response(
            200, {"data": [{"id": m} for m in upstream_models]}
        )
        fake_client = _FakeAsyncClient(fake_response)
        with patch("providers.openai_provider.httpx.AsyncClient", return_value=fake_client):
            cached = await catalog.list_models("openai", live=True, force=True)

        assert cached.source == "live"
        assert cached.warning == ""
        # Sorted because OpenAIProvider.sort()s before storing — but the
        # critical invariant is that we're seeing the upstream ids, not
        # the seeded fallbacks.
        assert set(cached.models) == set(upstream_models)
        # The hardcoded fallback list contains gpt-4o-mini; if we
        # accidentally short-circuited to the fallback path it would
        # leak into the response.
        assert "gpt-4o-mini" not in cached.models

    @pytest.mark.asyncio
    async def test_live_fetch_calls_models_endpoint(self, catalog):
        adapter = OpenAIProvider(api_key="sk-test")
        catalog.register_adapter(adapter)
        fake = _FakeAsyncClient(_httpx_response(200, {"data": [{"id": "gpt-x"}]}))
        with patch("providers.openai_provider.httpx.AsyncClient", return_value=fake):
            await catalog.list_models("openai", live=True, force=True)
        assert any("/models" in url for url in fake.calls)


# ----------------------------------------------------------------------
# Live fetch — 401 surfaces warning + falls back
# ----------------------------------------------------------------------


class TestLiveFetch401SurfacesWarning:
    @pytest.mark.asyncio
    async def test_401_falls_back_to_hardcoded_with_warning(self, catalog):
        """A 401 must NOT silently render the fallback list.

        The picker is allowed to render the seeded list as a
        last-resort safety net, but the response must carry a warning
        the UI can show as a "provider rejected the API key" chip so
        the user understands why no live models showed up.
        """
        adapter = OpenAIProvider(api_key="sk-bad")
        catalog.register_adapter(adapter)

        fake = _FakeAsyncClient(_httpx_response(401, {"error": "unauthorized"}))
        with patch("providers.openai_provider.httpx.AsyncClient", return_value=fake):
            cached = await catalog.list_models("openai", live=True, force=True)

        assert cached.warning != ""
        assert "401" in cached.warning or "rejected" in cached.warning.lower()
        # source must NOT be "live" — that would imply we trusted the
        # 401 response body, which we don't.
        assert cached.source in {"fallback", "cache"}
        # We still surface *some* model list so the picker isn't blank.
        assert len(cached.models) > 0


# ----------------------------------------------------------------------
# Disk cache TTL — 7-hour-old entry triggers refetch
# ----------------------------------------------------------------------


class _FakeRefreshAdapter(BaseProvider):
    provider_id = "openai"
    display_name = "OpenAI"
    _models = ["fallback-only"]

    def __init__(self, fresh_models: list[str]) -> None:
        self._fresh = list(fresh_models)
        self.refresh_calls = 0

    async def chat(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def refresh_models(self) -> list[str]:
        self.refresh_calls += 1
        return list(self._fresh)


class TestDiskCacheTTL:
    @pytest.mark.asyncio
    async def test_seven_hour_old_entry_triggers_refetch(self, catalog):
        """A cache entry older than the 6-hour TTL must refetch live."""
        # Seed a cached entry as if persisted 7 hours ago.
        seven_hours_ago = time.time() - 7 * 3600
        catalog._models["openai"] = CachedModelList(
            models=["stale-cached-model"],
            last_refresh=seven_hours_ago,
            source="cache",
        )
        fresh_adapter = _FakeRefreshAdapter(fresh_models=["fresh-from-live"])
        catalog.register_adapter(fresh_adapter)

        out = await catalog.list_models("openai", live=True)

        assert fresh_adapter.refresh_calls == 1
        assert out.models == ["fresh-from-live"]
        assert out.source == "live"

    @pytest.mark.asyncio
    async def test_default_ttl_is_six_hours(self):
        """Pin the documented TTL — 6h not 24h."""
        assert DEFAULT_CACHE_TTL_SECONDS == 6 * 3600

    @pytest.mark.asyncio
    async def test_within_ttl_does_not_refetch(self, catalog):
        adapter = _FakeRefreshAdapter(fresh_models=["m1"])
        catalog.register_adapter(adapter)
        await catalog.list_models("openai", live=True, force=True)
        adapter.refresh_calls = 0
        # Second call within TTL must hit cache.
        await catalog.list_models("openai", live=True, force=False)
        assert adapter.refresh_calls == 0


# ----------------------------------------------------------------------
# configure() invalidates cache so post-key-save fetches go live
# ----------------------------------------------------------------------


class TestConfigureInvalidatesCache:
    @pytest.mark.asyncio
    async def test_configure_drops_stale_cache(self, catalog):
        """After saving a key the next list_models() must go live.

        Repro of the user-visible bug: user pastes a working key, picker
        keeps showing the pre-key model list because the cache is
        warm. ``configure()`` must invalidate so the very next call
        re-fetches with the new credentials.
        """
        catalog._models["openai"] = CachedModelList(
            models=["pre-key-model"],
            last_refresh=time.time(),
            source="cache",
        )
        adapter = _FakeRefreshAdapter(fresh_models=["post-key-model"])
        catalog.register_adapter(adapter)

        catalog.configure("openai", api_key="sk-fresh")
        # configure() should re-bind the adapter; re-register our fake
        # because the catalog just clobbered it with a real OpenAI one.
        catalog.register_adapter(adapter)

        out = await catalog.list_models("openai", live=True)
        assert adapter.refresh_calls == 1
        assert out.models == ["post-key-model"]
        assert out.source == "live"

    @pytest.mark.asyncio
    async def test_invalidate_models_explicit(self, catalog):
        catalog._models["openai"] = CachedModelList(
            models=["x"], last_refresh=time.time(), source="cache"
        )
        catalog._warnings["openai"] = "stale warning"
        catalog.invalidate_models("openai")
        assert "openai" not in catalog._models
        assert "openai" not in catalog._warnings


# ----------------------------------------------------------------------
# Warning persists across calls until next successful refresh
# ----------------------------------------------------------------------


class TestWarningPersistence:
    @pytest.mark.asyncio
    async def test_warning_cleared_on_next_successful_refresh(self, catalog):
        adapter = OpenAIProvider(api_key="sk-bad")
        catalog.register_adapter(adapter)
        with patch(
            "providers.openai_provider.httpx.AsyncClient",
            return_value=_FakeAsyncClient(_httpx_response(401, {})),
        ):
            failed = await catalog.list_models("openai", live=True, force=True)
        assert failed.warning != ""

        # Next refresh succeeds — warning must be cleared.
        adapter._api_key = "sk-good"
        with patch(
            "providers.openai_provider.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                _httpx_response(200, {"data": [{"id": "gpt-z"}]})
            ),
        ):
            ok = await catalog.list_models("openai", live=True, force=True)
        assert ok.warning == ""
        assert ok.source == "live"
        assert "gpt-z" in ok.models
