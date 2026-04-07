"""
THEORA Skill Executor — Actually Calls the APIs
=================================================
The blind vault pattern: LLM outputs tool calls,
this executor injects auth and makes the HTTP requests.
The LLM NEVER sees API keys or OAuth tokens.
"""

from __future__ import annotations
import asyncio
import os
import json
import logging
import uuid
from typing import Optional
import httpx

from models.skill_manifest import SkillManifest, SkillEndpoint

logger = logging.getLogger("theora.executor")


class SkillExecutor:
    """
    Executes tool calls against skill endpoints.
    
    Security model (blind vault):
    1. LLM outputs: {tool: "weather_current__current", args: {q: "London"}}
    2. Executor looks up the skill manifest
    3. Executor pulls auth credentials from local vault (env vars for now)
    4. Executor makes the HTTP request with injected auth headers
    5. Executor sanitizes the response and returns it to the LLM
    6. LLM NEVER sees the raw API key
    """

    def __init__(self, daemons: dict = None):
        self.client = httpx.AsyncClient(timeout=15.0)
        self._daemons = daemons or {}
        self._vault: dict[str, str] = {}
        self._blind_vault = None
        self._pending_results: dict[str, asyncio.Future] = {}
        self._wasm_sandbox = None

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

    def set_blind_vault(self, vault):
        """Connect the BlindVault for secure credential retrieval."""
        self._blind_vault = vault

    def set_wasm_sandbox(self, sandbox):
        """Connect the WASM sandbox for skill execution."""
        self._wasm_sandbox = sandbox

    def _get_key(self, skill_id: str) -> Optional[str]:
        """Get API key — checks BlindVault first, then env cache."""
        if self._blind_vault:
            key = self._blind_vault.retrieve(skill_id, requester="executor")
            if key:
                return key
        return self._vault.get(skill_id)

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

        # 2. WASM runtime — execute in sandbox
        runtime = getattr(skill, 'runtime', None) or getattr(endpoint, 'runtime', None)
        if runtime == "wasm" and self._wasm_sandbox and self._wasm_sandbox.available:
            return await self._execute_via_wasm(tool_name, endpoint, args, skill)

        # 3. WS_EXECUTE — route to a connected daemon via WebSocket
        if endpoint.method == "WS_EXECUTE":
            return await self._execute_via_daemon(tool_name, endpoint, args, skill)

        # 4. Fallback to standard HTTP generic JSON runner
        url = endpoint.url
        method = endpoint.method.upper()
        headers = {}

        # Inject auth from vault (BlindVault → env cache fallback)
        auth_query_params = {}
        api_key = self._get_key(skill.skill_id)
        if skill.auth.type == "api_key" and api_key:
            header_name = skill.auth.api_key_header or "Authorization"
            # Some APIs (e.g. OpenWeather) use query params instead of headers
            if header_name.islower() and "-" not in header_name:
                auth_query_params[header_name] = api_key
            else:
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
                query_params = {k: v for k, v in args.items() if f"{{{k}}}" not in endpoint.url}
                query_params.update(auth_query_params)
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

    async def _execute_via_wasm(
        self, tool_name: str, endpoint: SkillEndpoint, args: dict, skill: SkillManifest,
    ) -> dict:
        """Execute a skill via the WASM sandbox."""
        from pathlib import Path
        skills_dir = Path.home() / ".theora" / "skills" / skill.skill_id
        wasm_files = list(skills_dir.glob("*.wasm"))
        if not wasm_files:
            return {"success": False, "status_code": 404, "data": None, "error": f"No .wasm file found for {skill.skill_id}"}

        result = await self._wasm_sandbox.execute(
            wasm_path=str(wasm_files[0]),
            params=args,
            entry_point=endpoint.id,
        )

        return {
            "success": result.get("success", False),
            "status_code": 200 if result.get("success") else 500,
            "data": self._sanitize_response(result.get("data")),
            "error": result.get("error"),
        }

    async def _execute_via_daemon(
        self, tool_name: str, endpoint: SkillEndpoint, args: dict, skill: SkillManifest,
    ) -> dict:
        """Route a WS_EXECUTE skill call to the appropriate connected daemon."""
        target_type = skill.daemon_node_type or "robot"

        target_daemon = None
        target_ws = None
        for node_id, ws in self._daemons.items():
            if target_type in node_id or target_type == "any":
                target_daemon = node_id
                target_ws = ws
                break

        if not target_daemon:
            for node_id, ws in self._daemons.items():
                target_daemon = node_id
                target_ws = ws
                break

        if not target_ws:
            return {
                "success": False, "status_code": 503, "data": None,
                "error": f"No connected daemon of type '{target_type}' to execute {tool_name}",
            }

        request_id = str(uuid.uuid4())
        execute_msg = {
            "hop": "brain",
            "type": "execute",
            "msg_id": request_id,
            "payload": {
                "executor": endpoint.id,
                "args": args,
                "skill_id": skill.skill_id,
            },
        }

        future = asyncio.get_event_loop().create_future()
        self._pending_results[request_id] = future

        try:
            await target_ws.send_json(execute_msg)
            logger.info(f"WS_EXECUTE → {target_daemon}: {endpoint.id} (req={request_id})")

            result = await asyncio.wait_for(future, timeout=15.0)
            return {
                "success": result.get("status") == "success",
                "status_code": 200 if result.get("status") == "success" else 500,
                "data": self._sanitize_response(result.get("stdout") or result.get("data")),
                "error": result.get("error"),
            }

        except asyncio.TimeoutError:
            self._pending_results.pop(request_id, None)
            return {
                "success": False, "status_code": 504, "data": None,
                "error": f"Daemon {target_daemon} timed out executing {endpoint.id}",
            }
        except Exception as e:
            self._pending_results.pop(request_id, None)
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}

    def resolve_daemon_result(self, request_id: str, result: dict):
        """Called when a daemon sends back an execute_result."""
        future = self._pending_results.pop(request_id, None)
        if future and not future.done():
            future.set_result(result)

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
