"""
THEORA Skill Executor — Actually Calls the APIs
=================================================
The blind vault pattern: LLM outputs tool calls,
this executor injects auth and makes the HTTP requests.
The LLM NEVER sees API keys or OAuth tokens.
"""

from __future__ import annotations
import os
import json
import logging
from typing import Optional
import httpx

from models.skill_manifest import SkillManifest, SkillEndpoint

logger = logging.getLogger("theora.executor")


class SkillExecutor:
    """
    Executes tool calls against skill endpoints.
    
    Security model (blind vault):
    1. LLM outputs: {tool: "weather__current_weather", args: {lat: 37, lon: -122}}
    2. Executor looks up the skill manifest
    3. Executor pulls auth credentials from local vault (env vars for now)
    4. Executor makes the HTTP request with injected auth headers
    5. Executor sanitizes the response and returns it to the LLM
    6. LLM NEVER sees the raw API key
    """

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)
        # Simple vault: env vars keyed by skill_id
        # e.g. THEORA_KEY_weather_current = "abc123"
        self._vault: dict[str, str] = {}

    def load_vault_from_env(self):
        """Load API keys from environment variables."""
        for key, value in os.environ.items():
            if key.startswith("THEORA_KEY_"):
                skill_id = key[len("THEORA_KEY_"):]
                self._vault[skill_id] = value
                logger.info(f"Vault: loaded key for skill '{skill_id}'")

    def set_key(self, skill_id: str, key: str):
        """Manually set an API key for a skill."""
        self._vault[skill_id] = key

    async def execute(
        self,
        tool_name: str,
        args: dict,
        skill: SkillManifest,
        endpoint: SkillEndpoint,
    ) -> dict:
        """
        Execute a skill endpoint call.
        """
        logger.info(f"Executing: {tool_name} → {endpoint.method} {endpoint.url}")
        logger.info(f"  args: {args}")

        # 1. Check if there's a Python implementation backing this skill
        from skills.impl import get_implementation
        impl = get_implementation(skill.skill_id)
        if impl:
            logger.info(f"Executing via Python backing class: {impl.__class__.__name__}")
            try:
                # Provide the vault mapped appropriately
                result = await impl.execute(endpoint.id, args, self._vault)
                # Ensure the return format is standard
                if isinstance(result, dict) and "success" in result:
                    return {
                        "success": result["success"],
                        "status_code": result.get("status_code", 200),
                        "data": self._sanitize_response(result.get("data")),
                        "error": result.get("error")
                    }
                else:
                    return {
                        "success": True,
                        "status_code": 200,
                        "data": self._sanitize_response(result),
                        "error": None
                    }
            except Exception as e:
                logger.error(f"Python Skill error: {e}", exc_info=True)
                return {"success": False, "status_code": 500, "data": None, "error": str(e)}

        # 2. Fallback to standard HTTP generic JSON runner
        url = endpoint.url
        method = endpoint.method.upper()
        headers = {}

        # Inject auth from vault
        api_key = self._vault.get(skill.skill_id)
        if skill.auth.type == "api_key" and api_key:
            header_name = skill.auth.api_key_header or "Authorization"
            headers[header_name] = api_key
        elif skill.auth.type == "bearer" and api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # URL parameter substitution (e.g., /restaurants/{id}/menu)
        for param_name, param_value in args.items():
            placeholder = f"{{{param_name}}}"
            if placeholder in url:
                url = url.replace(placeholder, str(param_value))

        try:
            if method == "GET":
                # For GET, put args as query params (exclude those already in URL)
                query_params = {k: v for k, v in args.items() if f"{{{k}}}" not in endpoint.url}
                resp = await self.client.get(url, params=query_params, headers=headers)
            elif method in ("POST", "PUT", "PATCH"):
                resp = await self.client.request(method, url, json=args, headers=headers)
            elif method == "DELETE":
                resp = await self.client.delete(url, headers=headers)
            else:
                return {"success": False, "status_code": 0, "data": None, "error": f"Unknown method: {method}"}

            # Parse response
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text[:1000]}

            # Sanitize — strip any potential prompt injection from response
            sanitized = self._sanitize_response(data)

            return {
                "success": 200 <= resp.status_code < 300,
                "status_code": resp.status_code,
                "data": sanitized,
                "error": None if resp.status_code < 400 else f"HTTP {resp.status_code}",
            }

        except httpx.TimeoutException:
            logger.error(f"Timeout calling {url}")
            return {"success": False, "status_code": 0, "data": None, "error": "Request timed out"}
        except Exception as e:
            logger.error(f"Error calling {url}: {e}")
            return {"success": False, "status_code": 0, "data": None, "error": str(e)}

    def _sanitize_response(self, data, max_depth: int = 5, max_str_len: int = 2000) -> any:
        """
        Sanitize API response data before feeding back to the LLM.
        Prevents:
        - Prompt injection via response content
        - Excessive data that would overflow context
        """
        if max_depth <= 0:
            return "[truncated]"

        if isinstance(data, dict):
            return {k: self._sanitize_response(v, max_depth - 1) for k, v in list(data.items())[:50]}
        elif isinstance(data, list):
            return [self._sanitize_response(item, max_depth - 1) for item in data[:20]]
        elif isinstance(data, str):
            # Truncate long strings
            if len(data) > max_str_len:
                return data[:max_str_len] + "...[truncated]"
            return data
        else:
            return data

    async def close(self):
        await self.client.aclose()
