"""Localhost-only auth helpers for bootstrapping the browser client.

The browser Glass Brain and Settings UI need the auto-generated
``FERAL_API_KEY`` stored in ``~/.feral/api_key`` so they can authenticate
WebSocket + REST calls. Since these pages are usually opened from
``http://localhost:9090`` on the user's own machine, we expose a
loopback-only endpoint that hands back the local key. Requests from
non-loopback origins are rejected regardless of existing auth.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

from api.keys import load_api_key
from security.session_auth import is_localhost

logger = logging.getLogger("feral.api.auth")

router = APIRouter()


def _client_host(request: Request) -> str:
    client = request.client
    if client and client.host:
        return client.host
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or ""


@router.get("/api/auth/local-key")
async def get_local_api_key(request: Request) -> Response:
    """Return the FERAL API key — but ONLY to loopback callers.

    This lets the in-browser client on ``localhost`` seed
    ``localStorage.feral_api_key`` on first load without the user having
    to open a terminal and copy the file.
    """
    host = _client_host(request)
    if not is_localhost(host):
        return Response(
            content='{"error": "local-only endpoint"}',
            status_code=403,
            media_type="application/json",
        )
    key = load_api_key()
    if not key:
        return Response(
            content='{"error": "no api key configured"}',
            status_code=404,
            media_type="application/json",
        )
    return {"api_key": key}
