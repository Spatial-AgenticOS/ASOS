"""
Tests for multi-provider ``WebSearchSkill`` execution and error paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from skills.impl.web_search import SearchResult, WebSearchEngine, WebSearchSkill


@pytest.fixture
def skill() -> WebSearchSkill:
    return WebSearchSkill()


class TestWebSearchExecute:
    @pytest.mark.asyncio
    async def test_execute_search_returns_results_with_expected_fields(self, skill: WebSearchSkill) -> None:
        fake = [
            SearchResult(
                title="Example",
                url="https://example.com",
                snippet="Snippet body from provider",
                score=1.0,
            )
        ]
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
    async def test_missing_query_returns_error(self, skill: WebSearchSkill) -> None:
        out = await skill.execute("web_search", {}, {})

        assert out["success"] is False
        assert out["status_code"] == 400
        assert out["data"] is None
        assert out["error"] is not None

    @pytest.mark.asyncio
    async def test_engine_orders_tavily_brave_then_ddg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        eng = WebSearchEngine.from_env({})
        names = [p.name for p in eng.providers]
        assert names == ["duckduckgo"]

        monkeypatch.setenv("TAVILY_API_KEY", "t1")
        monkeypatch.setenv("BRAVE_API_KEY", "b1")
        eng2 = WebSearchEngine.from_env({})
        names2 = [p.name for p in eng2.providers]
        assert names2 == ["tavily", "brave", "duckduckgo"]
