from typing import Any, Dict
import httpx
from skills.base import BaseSkill
from skills.impl import register_skill

@register_skill
class WebSearchSkill(BaseSkill):
    """
    Real integration with Tavily AI Search API for Agentic OS.
    Tavily is designed specifically for LLM context injection.
    """
    
    def __init__(self):
        super().__init__(skill_id="web_search")
        self.client = httpx.AsyncClient(timeout=15.0)

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        
        # We need the TAVILY key
        api_key = self.get_api_key(vault, fallback_env="TAVILY_API_KEY")
        
        if not api_key:
            return {
                "success": False,
                "status_code": 401,
                "data": None,
                "error": "Tavily API key not found. Set THEORA_KEY_web_search or TAVILY_API_KEY env var."
            }

        query = args.get("query") or args.get("q") or args.get("search") or args.get("text", "")
        if not query:
            return {
                "success": False,
                "status_code": 400,
                "data": None,
                "error": "Missing search query. Provide 'query' or 'q' parameter."
            }

        # Tavily endpoint mapping
        if endpoint_id == "web_search":
            return await self._call_tavily(query, api_key, search_depth="basic", include_answer=False)
        elif endpoint_id == "instant_answer":
            return await self._call_tavily(query, api_key, search_depth="advanced", include_answer=True)
        else:
            return {
                "success": False,
                "status_code": 404,
                "data": None,
                "error": f"Unknown endpoint_id: {endpoint_id}"
            }

    async def _call_tavily(self, query: str, api_key: str, search_depth: str, include_answer: bool) -> Dict[str, Any]:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": search_depth,
            "include_answer": include_answer,
            "include_images": False,
            "include_raw_content": False,
            "max_results": 5
        }
        
        try:
            resp = await self.client.post(url, json=payload)
            if resp.status_code >= 400:
                print(f"Tavily error: {resp.status_code} - {resp.text}")
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "data": None,
                    "error": resp.text[:200]
                }
            
            data = resp.json()
            
            # Reformat to be clean for LLM context
            results = data.get("results", [])
            clean_results = []
            for r in results:
                clean_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")
                })
                
            out_data = {
                "results": clean_results
            }
            if data.get("answer"):
                out_data["answer"] = data["answer"]
                
            return {
                "success": True,
                "status_code": 200,
                "data": out_data,
                "error": None
            }
            
        except httpx.RequestError as e:
            return {
                "success": False,
                "status_code": 0,
                "data": None,
                "error": str(e)
            }
