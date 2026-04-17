"""
Tests for multi-provider ``WebSearchSkill`` execution and error paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skills.impl.web_search import (
    DuckDuckGoProvider,
    SearchResult,
    WebSearchEngine,
    WebSearchSkill,
)


@pytest.fixture
def skill() -> WebSearchSkill:
    return WebSearchSkill()


class TestWebSearchExecute:
    @pytest.mark.asyncio
    async def test_execute_search_returns_results_with_expected_fields(self, skill: WebSearchSkill) -> None:
        fake = (
            [
                SearchResult(
                    title="Example",
                    url="https://example.com",
                    snippet="Snippet body from provider",
                    score=1.0,
                )
            ],
            "tavily",
        )
        with patch.object(WebSearchEngine, "search", new_callable=AsyncMock, return_value=fake):
            out = await skill.execute(
                "web_search",
                {"query": "test"},
                {"web_search": "tvly-test-key"},
            )

        assert out["success"] is True
        assert out["status_code"] == 200
        assert out["data"] is not None
        results = out["data"]["results"]
        assert len(results) == 1
        r0 = results[0]
        assert r0["title"] == "Example"
        assert r0["url"] == "https://example.com"
        assert r0["snippet"] == "Snippet body from provider"
        assert r0["score"] == 1.0

    @pytest.mark.asyncio
    async def test_provider_used_field_appears(self, skill: WebSearchSkill) -> None:
        fake = (
            [SearchResult(title="R", url="https://r.com", snippet="s", score=1.0)],
            "brave",
        )
        with patch.object(WebSearchEngine, "search", new_callable=AsyncMock, return_value=fake):
            out = await skill.execute("web_search", {"query": "q"}, {})
        assert out["data"]["provider_used"] == "brave"

    @pytest.mark.asyncio
    async def test_missing_query_returns_error(self, skill: WebSearchSkill) -> None:
        out = await skill.execute("web_search", {}, {})

        assert out["success"] is False
        assert out["status_code"] == 400
        assert out["data"] is None
        assert out["error"] is not None

    @pytest.mark.asyncio
    async def test_engine_orders_tavily_brave_then_ddg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "TAVILY_API_KEY", "BRAVE_API_KEY", "EXA_API_KEY",
            "PERPLEXITY_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID",
            "SEARXNG_URL",
        ):
            monkeypatch.delenv(var, raising=False)
        eng = WebSearchEngine.from_env({})
        names = [p.name for p in eng.providers]
        assert names == ["duckduckgo"]

        monkeypatch.setenv("TAVILY_API_KEY", "t1")
        monkeypatch.setenv("BRAVE_API_KEY", "b1")
        eng2 = WebSearchEngine.from_env({})
        names2 = [p.name for p in eng2.providers]
        assert names2 == ["tavily", "brave", "duckduckgo"]


class TestSearchFailover:
    @pytest.mark.asyncio
    async def test_graceful_fallback_when_provider_raises(self) -> None:
        """When the first provider raises, engine falls through to next."""
        p1 = MagicMock()
        p1.name = "broken"
        p1.search = AsyncMock(side_effect=RuntimeError("boom"))
        p2 = MagicMock()
        p2.name = "good"
        p2.search = AsyncMock(return_value=[
            SearchResult(title="OK", url="https://ok.com", snippet="ok", score=1.0),
        ])
        engine = WebSearchEngine([p1, p2])
        results, provider = await engine.search("test")
        assert provider == "good"
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_ddg_missing_does_not_crash(self) -> None:
        """DDG ImportError is handled; falls back to HTTP API."""
        saved = DuckDuckGoProvider._ddgs_available
        try:
            DuckDuckGoProvider._ddgs_available = False
            ddg = DuckDuckGoProvider()
            ddg._client = MagicMock()
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"Abstract": "", "RelatedTopics": []}
            ddg._client.get = AsyncMock(return_value=resp)

            results = await ddg.search("test query", max_results=3)
            assert isinstance(results, list)
        finally:
            DuckDuckGoProvider._ddgs_available = saved
