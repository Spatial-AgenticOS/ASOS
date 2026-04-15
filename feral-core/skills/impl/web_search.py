from __future__ import annotations

import hashlib
import logging
import os
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skills.web_search")


# ---------------------------------------------------------------------------
# Result cache + deduplication
# ---------------------------------------------------------------------------

class SearchCache:
    """TTL-bounded, size-bounded cache keyed on normalised query text."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 200):
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size

    def get(self, query: str) -> list[dict] | None:
        key = hashlib.md5(query.lower().strip().encode()).hexdigest()
        if key in self._cache:
            ts, results = self._cache[key]
            if _time.time() - ts < self._ttl:
                return results
            del self._cache[key]
        return None

    def set(self, query: str, results: list[dict]) -> None:
        if len(self._cache) >= self._max_size:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        key = hashlib.md5(query.lower().strip().encode()).hexdigest()
        self._cache[key] = (_time.time(), results)


def _deduplicate(results: list[SearchResult]) -> list[SearchResult]:
    """Remove duplicate URLs while preserving order; keep URL-less items."""
    seen_urls: set[str] = set()
    deduped: list[SearchResult] = []
    for r in results:
        if r.url and r.url in seen_urls:
            continue
        if r.url:
            seen_urls.add(r.url)
        deduped.append(r)
    return deduped


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


class ExaSearchProvider(SearchProvider):
    """Exa — semantic search API."""

    name = "exa"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = httpx.AsyncClient(base_url="https://api.exa.ai", timeout=15)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        response = await self._client.post(
            "/search",
            json={
                "query": query,
                "numResults": max_results,
                "type": "auto",
                "useAutoprompt": True,
                "contents": {"text": {"maxCharacters": 1000}},
            },
            headers={
                "x-api-key": self._api_key,
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=(r.get("text", "") or "")[:500],
                score=float(max(0, len(data.get("results", [])) - i)),
            )
            for i, r in enumerate(data.get("results", []))
        ]


class SearXNGProvider(SearchProvider):
    """SearXNG — self-hosted meta-search."""

    name = "searxng"

    def __init__(self, base_url: str = "http://localhost:8080"):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=15)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        response = await self._client.get(
            "/search",
            params={"q": query, "format": "json", "pageno": 1},
        )
        response.raise_for_status()
        data = response.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=(r.get("content", "") or "")[:500],
                score=float(max(0, max_results - i)),
            )
            for i, r in enumerate(data.get("results", [])[:max_results])
        ]


class PerplexityProvider(SearchProvider):
    """Perplexity — AI-powered search."""

    name = "perplexity"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url="https://api.perplexity.ai", timeout=30,
        )

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
            },
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        citations = data.get("citations", [])
        if citations:
            return [
                SearchResult(
                    title=f"Perplexity Result {i + 1}",
                    url=c,
                    snippet=content[:500] if i == 0 else "",
                    score=float(max(0, len(citations) - i)),
                )
                for i, c in enumerate(citations[:max_results])
            ]
        return [
            SearchResult(
                title="Perplexity Answer",
                url="",
                snippet=content[:1000],
                score=1.0,
            )
        ]


class GoogleCSEProvider(SearchProvider):
    """Google Custom Search Engine."""

    name = "google_cse"

    def __init__(self, api_key: str, cse_id: str):
        self._api_key = api_key
        self._cse_id = cse_id
        self._client = httpx.AsyncClient(timeout=15)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        response = await self._client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self._api_key,
                "cx": self._cse_id,
                "q": query,
                "num": min(max_results, 10),
            },
        )
        response.raise_for_status()
        data = response.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
                score=float(max(0, len(data.get("items", [])) - i)),
            )
            for i, r in enumerate(data.get("items", []))
        ]


class WebSearchEngine:
    """Ordered search providers with failover and result caching."""

    def __init__(self, providers: list[SearchProvider]):
        self.providers = providers
        self._cache = SearchCache()

    @classmethod
    def from_env(cls, vault: Optional[Dict[str, str]] = None) -> "WebSearchEngine":
        vault = vault or {}
        providers: list[SearchProvider] = []

        tavily_key = vault.get("web_search") or os.environ.get("TAVILY_API_KEY")
        brave_key = os.environ.get("BRAVE_API_KEY")
        exa_key = os.environ.get("EXA_API_KEY")
        pplx_key = os.environ.get("PERPLEXITY_API_KEY")
        google_key = os.environ.get("GOOGLE_API_KEY")
        google_cse = os.environ.get("GOOGLE_CSE_ID")
        searxng_url = os.environ.get("SEARXNG_URL")

        if tavily_key:
            providers.append(TavilyProvider(tavily_key))
        if brave_key:
            providers.append(BraveProvider(brave_key))
        if exa_key:
            providers.append(ExaSearchProvider(exa_key))
        if pplx_key:
            providers.append(PerplexityProvider(pplx_key))
        if google_key and google_cse:
            providers.append(GoogleCSEProvider(google_key, google_cse))
        if searxng_url:
            providers.append(SearXNGProvider(searxng_url))

        providers.append(DuckDuckGoProvider())
        return cls(providers)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        cached = self._cache.get(query)
        if cached is not None:
            logger.debug("search cache hit for %r", query)
            return [SearchResult(**r) for r in cached]

        last_err: Optional[Exception] = None
        for p in self.providers:
            try:
                results = await p.search(query, max_results=max_results)
                if results:
                    results = _deduplicate(results)
                    self._cache.set(
                        query,
                        [{"title": r.title, "url": r.url, "snippet": r.snippet, "score": r.score} for r in results],
                    )
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
                    return _deduplicate(results), answer
                except Exception as e:
                    logger.debug("tavily instant: %s", e)
        for p in self.providers:
            if isinstance(p, DuckDuckGoProvider):
                try:
                    ans = await p.instant_answer_only(query)
                    results = await p.search(query, max_results=max_results)
                    return _deduplicate(results), ans
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
    Web search with multi-provider failover: Tavily, Brave, Exa, Perplexity,
    Google CSE, SearXNG, then DuckDuckGo.  Results are cached and deduplicated.
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
