"""
TheoraPlugin — Base class for all THEORA plugins.

A plugin bundles tools, device adapters, and UI components into a single
installable package that the Brain discovers and loads at startup.
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger("theora.sdk.plugin")


class TheoraPlugin:
    """Base class for THEORA plugins.

    Subclass this to create a plugin. Decorate methods with @theora_tool
    to expose them as agent tools.

    Example::

        class WeatherPlugin(TheoraPlugin):
            name = "weather"
            description = "Real-time weather data"

            @theora_tool(description="Get current weather for a city")
            async def current(self, city: str) -> dict:
                ...
    """

    name: str = ""
    description: str = ""
    version: str = "0.1.0"
    author: str = ""

    def __init__(self):
        if not self.name:
            self.name = type(self).__name__.lower().replace("plugin", "")
        self._tools: dict[str, Any] = {}
        self._discover_tools()

    def _discover_tools(self):
        """Find all methods decorated with @theora_tool."""
        for attr_name in dir(self):
            method = getattr(self, attr_name, None)
            if callable(method) and hasattr(method, "_theora_tool_meta"):
                meta = method._theora_tool_meta
                tool_id = meta.get("name") or attr_name
                self._tools[tool_id] = {
                    "handler": method,
                    "meta": meta,
                }

    @property
    def tools(self) -> dict[str, dict]:
        return dict(self._tools)

    def to_manifest(self) -> dict:
        """Generate a THEORA skill manifest from this plugin's tools."""
        endpoints = []
        for tool_id, info in self._tools.items():
            meta = info["meta"]
            params = []
            for pname, pinfo in (meta.get("parameters") or {}).items():
                params.append({
                    "name": pname,
                    "type": pinfo.get("type", "string"),
                    "description": pinfo.get("description", ""),
                    "required": pinfo.get("required", True),
                })
            endpoints.append({
                "id": tool_id,
                "method": "POST",
                "url": f"plugin://{self.name}/{tool_id}",
                "description": meta.get("description", ""),
                "params": params,
            })
        return {
            "skill_id": self.name,
            "version": self.version,
            "description": self.description,
            "brand": {"name": self.name.replace("_", " ").title(), "icon": "puzzle"},
            "endpoints": endpoints,
            "trigger_phrases": [],
            "categories": ["plugin"],
        }

    async def execute(self, endpoint_id: str, args: dict, vault: dict) -> dict:
        """Execute a tool endpoint. Called by the Brain's SkillExecutor."""
        tool = self._tools.get(endpoint_id)
        if not tool:
            return {"success": False, "status_code": 404, "data": None, "error": f"Unknown endpoint: {endpoint_id}"}
        try:
            result = await tool["handler"](**args)
            return {"success": True, "status_code": 200, "data": result, "error": None}
        except Exception as e:
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}

    async def on_load(self):
        """Called when the plugin is loaded by the Brain. Override for setup."""
        pass

    async def on_unload(self):
        """Called when the plugin is unloaded. Override for cleanup."""
        pass
