from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("theora.skills.web_search")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0


class SearchProvider(ABC):
    """Pluggable web search backend."""

    name: str = "base"

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError


class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None):
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "max_results": max_results,
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        out: list[SearchResult] = []
        for i, r in enumerate(data.get("results", [])):
            out.append(
                SearchResult(
                    title=r.get("title", "") or "",
                    url=r.get("url", "") or "",
                    snippet=r.get("content", "") or "",
                    score=float(max(0, len(data.get("results", [])) - i)),
                )
            )
        return out

    async def search_with_answer(self, query: str, max_results: int = 5) -> tuple[list[SearchResult], Optional[str]]:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "include_images": False,
            "include_raw_content": False,
            "max_results": max_results,
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        results: list[SearchResult] = []
        for i, r in enumerate(data.get("results", [])):
            results.append(
                SearchResult(
                    title=r.get("title", "") or "",
                    url=r.get("url", "") or "",
                    snippet=r.get("content", "") or "",
                    score=float(max(0, len(data.get("results", [])) - i)),
                )
            )
        answer = data.get("answer")
        return results, answer if isinstance(answer, str) else None


class BraveProvider(SearchProvider):
    name = "brave"

    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None):
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        url = "https://api.search.brave.com/res/v1/web/search"
        params = {"q": query, "count": max_results}
        headers = {"X-Subscription-Token": self._api_key, "Accept": "application/json"}
        resp = await self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        web = data.get("web") or {}
        raw = web.get("results") or []
        out: list[SearchResult] = []
        for i, r in enumerate(raw):
            desc = r.get("description") or ""
            extra = r.get("extra_snippets") or []
            snippet = desc
            if extra and isinstance(extra, list) and extra:
                snippet = f"{desc} {' '.join(extra[:2])}".strip()
            out.append(
                SearchResult(
                    title=r.get("title", "") or "",
                    url=r.get("url", "") or "",
                    snippet=snippet,
                    score=float(max(0, len(raw) - i)),
                )
            )
        return out


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            from duckduckgo_search import DDGS

            out: list[SearchResult] = []
            with DDGS() as ddgs:
                for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                    out.append(
                        SearchResult(
                            title=str(r.get("title", "") or ""),
                            url=str(r.get("href", "") or r.get("url", "") or ""),
                            snippet=str(r.get("body", "") or ""),
                            score=float(max(0, max_results - i)),
                        )
                    )
            if out:
                return out
        except Exception as e:
            logger.debug("duckduckgo_search package failed: %s", e)

        return await self._instant_answer_http(query, max_results)

    async def instant_answer_only(self, query: str) -> Optional[str]:
        """Best-effort instant answer string (DDG JSON API)."""
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=1):
                    return str(r.get("body", ""))[:2000] or None
        except Exception as e:
            logger.debug("DDGS instant_answer_only: %s", e)
        data = await self._fetch_json_api(query)
        if data.get("Abstract"):
            return str(data["Abstract"])
        return None

    async def _fetch_json_api(self, query: str) -> dict[str, Any]:
        q = quote(query, safe="")
        u = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1"
        resp = await self._client.get(u)
        resp.raise_for_status()
        return resp.json()

    async def _instant_answer_http(self, query: str, max_results: int) -> list[SearchResult]:
        data = await self._fetch_json_api(query)
        out: list[SearchResult] = []
        if data.get("Abstract") and data.get("AbstractURL"):
            out.append(
                SearchResult(
                    title=str(data.get("Heading", "") or "Instant answer"),
                    url=str(data.get("AbstractURL", "")),
                    snippet=str(data.get("Abstract", "")),
                    score=10.0,
                )
            )
        for topic in (data.get("RelatedTopics") or [])[: max(0, max_results - len(out))]:
            if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                out.append(
                    SearchResult(
                        title=str(topic.get("Text", ""))[:200],
                        url=str(topic.get("FirstURL", "")),
                        snippet=str(topic.get("Text", "")),
                        score=5.0,
                    )
                )
            elif isinstance(topic, dict) and "Topics" in topic:
                for t in (topic.get("Topics") or [])[:max_results]:
                    if isinstance(t, dict) and t.get("Text") and t.get("FirstURL"):
                        out.append(
                            SearchResult(
                                title=str(t.get("Text", ""))[:200],
                                url=str(t.get("FirstURL", "")),
                                snippet=str(t.get("Text", "")),
                                score=3.0,
                            )
                        )
                    if len(out) >= max_results:
                        break
            if len(out) >= max_results:
                break
        return out[:max_results]


class WebSearchEngine:
    """Ordered search providers with failover."""

    def __init__(self, providers: list[SearchProvider]):
        self.providers = providers

    @classmethod
    def from_env(cls, vault: Optional[Dict[str, str]] = None) -> "WebSearchEngine":
        vault = vault or {}
        providers: list[SearchProvider] = []
        tavily_key = vault.get("web_search") or os.environ.get("TAVILY_API_KEY")
        brave_key = os.environ.get("BRAVE_API_KEY")
        if tavily_key:
            providers.append(TavilyProvider(tavily_key))
        if brave_key:
            providers.append(BraveProvider(brave_key))
        if not providers:
            providers.append(DuckDuckGoProvider())
        else:
            providers.append(DuckDuckGoProvider())
        return cls(providers)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        last_err: Optional[Exception] = None
        for p in self.providers:
            try:
                results = await p.search(query, max_results=max_results)
                if results:
                    return results
            except Exception as e:
                last_err = e
                logger.debug("provider %s failed: %s", p.name, e)
                continue
        if last_err:
            raise last_err
        return []

    async def search_instant(self, query: str, max_results: int = 5) -> tuple[list[SearchResult], Optional[str]]:
        for p in self.providers:
            if isinstance(p, TavilyProvider):
                try:
                    results, answer = await p.search_with_answer(query, max_results=max_results)
                    return results, answer
                except Exception as e:
                    logger.debug("tavily instant: %s", e)
        for p in self.providers:
            if isinstance(p, DuckDuckGoProvider):
                try:
                    ans = await p.instant_answer_only(query)
                    results = await p.search(query, max_results=max_results)
                    return results, ans
                except Exception as e:
                    logger.debug("ddg instant: %s", e)
        results = await self.search(query, max_results=max_results)
        return results, None


def _results_to_payload(results: list[SearchResult]) -> list[dict[str, Any]]:
    return [
        {
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet,
            "score": r.score,
        }
        for r in results
    ]


@register_skill
class WebSearchSkill(BaseSkill):
    """
    Web search with multi-provider failover: Tavily, Brave, then DuckDuckGo.
    """

    def __init__(self) -> None:
        super().__init__(skill_id="web_search")

    def _engine(self, vault: Dict[str, str]) -> WebSearchEngine:
        return WebSearchEngine.from_env(vault)

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        query = args.get("query") or args.get("q") or args.get("search") or args.get("text", "")
        if not query:
            return {
                "success": False,
                "status_code": 400,
                "data": None,
                "error": "Missing search query. Provide 'query' or 'q' parameter.",
            }

        max_results = int(args.get("max_results", 5) or 5)
        max_results = max(1, min(max_results, 20))

        engine = self._engine(vault)

        try:
            if endpoint_id == "web_search":
                results = await engine.search(query, max_results=max_results)
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"results": _results_to_payload(results)},
                    "error": None,
                }
            if endpoint_id == "instant_answer":
                results, answer = await engine.search_instant(query, max_results=max_results)
                out_data: Dict[str, Any] = {"results": _results_to_payload(results)}
                if answer:
                    out_data["answer"] = answer
                return {
                    "success": True,
                    "status_code": 200,
                    "data": out_data,
                    "error": None,
                }
            return {
                "success": False,
                "status_code": 404,
                "data": None,
                "error": f"Unknown endpoint_id: {endpoint_id}",
            }
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200] if e.response is not None else ""
            return {
                "success": False,
                "status_code": e.response.status_code if e.response is not None else 0,
                "data": None,
                "error": body or str(e),
            }
        except httpx.RequestError as e:
            return {"success": False, "status_code": 0, "data": None, "error": str(e)}
        except Exception as e:
            logger.exception("web_search execute failed")
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}
