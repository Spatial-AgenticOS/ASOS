"""
FeralClient — Connect to a running FERAL Brain via HTTP + WebSocket.

Usage::

    async with FeralClient("http://localhost:9090") as client:
        response = await client.chat("What's the weather?")
        print(response)

        dashboard = await client.get_dashboard()
        print(dashboard["skills_count"])
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, AsyncIterator
from contextlib import asynccontextmanager

import httpx

logger = logging.getLogger("feral.sdk.client")


class FeralClient:
    """HTTP + WebSocket client for the FERAL Brain API."""

    def __init__(self, base_url: str = "http://localhost:9090"):
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/v1/session"
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30)
        self._ws = None
        self._session_id: str | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self._http.aclose()
        if self._ws:
            await self._ws.close()

    async def health(self) -> dict:
        """Check brain health."""
        r = await self._http.get("/api/health")
        return r.json()

    async def get_dashboard(self) -> dict:
        """Get aggregated dashboard data."""
        r = await self._http.get("/api/dashboard")
        return r.json()

    async def get_system_info(self) -> dict:
        """Get system info (version, memory stats, etc.)."""
        r = await self._http.get("/api/system/info")
        return r.json()

    async def chat(self, message: str, session_id: str | None = None) -> str:
        """Send a text message and wait for the full response."""
        import websockets

        ws_url = self.ws_url
        async with websockets.connect(ws_url) as ws:
            greeting = json.loads(await ws.recv())
            sid = greeting.get("session_id", session_id or "sdk")

            await ws.send(json.dumps({
                "type": "text_command",
                "session_id": sid,
                "payload": {"text": message},
            }))

            response_parts = []
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                    msg = json.loads(raw)
                    if msg.get("type") == "text_response":
                        return msg["payload"]["text"]
                    elif msg.get("type") == "stream_delta":
                        if msg["payload"].get("is_final"):
                            return "".join(response_parts)
                        response_parts.append(msg["payload"].get("delta", ""))
                except asyncio.TimeoutError:
                    return "".join(response_parts) or "[timeout]"

    async def list_skills(self) -> list[dict]:
        """List all registered skills."""
        r = await self._http.get("/api/skills")
        data = r.json()
        return data.get("skills", data) if isinstance(data, dict) else data

    async def search_memory(self, query: str, limit: int = 10) -> list[dict]:
        """Search the agent's memory."""
        r = await self._http.get("/api/memory/search", params={"q": query, "limit": limit})
        return r.json().get("results", [])

    async def create_note(self, content: str, tags: list[str] | None = None) -> dict:
        """Create a memory note."""
        r = await self._http.post("/api/notes", json={"content": content, "tags": tags or []})
        return r.json()

    async def list_conversations(self, limit: int = 20) -> list[dict]:
        """List conversation threads."""
        r = await self._http.get("/api/conversations", params={"limit": limit})
        return r.json().get("conversations", [])

    async def invoke_skill(self, skill_id: str, endpoint: str, args: dict | None = None) -> dict:
        """Directly invoke a skill endpoint."""
        r = await self._http.post(f"/api/skills/{skill_id}/{endpoint}", json=args or {})
        return r.json()
