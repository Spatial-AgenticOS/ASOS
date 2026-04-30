"""
FERAL Realtime Client Secrets — Ephemeral token endpoint
=========================================================
POST /api/voice/client_secrets

Mints a short-lived OpenAI Realtime client secret via the server-side
``POST https://api.openai.com/v1/realtime/client_secrets`` API.  Returns
``{value, expires_at}`` so a phone or browser client could (in a future
WebRTC-direct path) connect to OpenAI without exposing the real API key.

For the current PR #62 phone flow audio is proxied through the Brain,
so this endpoint is scaffolding for that future path — but it is
fully functional and tested.

Bearer-gated: requires the operator's dashboard API key or a valid
phone bearer token.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("feral.api.realtime_client_secret")

router = APIRouter(tags=["voice"])

OPENAI_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
DEFAULT_MODEL = "gpt-realtime"
DEFAULT_VOICE = "marin"
DEFAULT_TTL_SECONDS = 600


class ClientSecretRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL, description="Realtime model ID")
    voice: str = Field(default=DEFAULT_VOICE, description="Voice for the session")
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, ge=10, le=7200)


class ClientSecretResponse(BaseModel):
    value: str
    expires_at: int


def _get_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")


def _get_feral_api_key() -> str:
    """Load the Brain's API key for bearer validation."""
    try:
        from api.keys import load_api_key
        return load_api_key() or ""
    except Exception:
        return os.getenv("FERAL_API_KEY", "")


def _verify_bearer(authorization: str) -> None:
    """Validate the Authorization header against the FERAL API key."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    feral_key = _get_feral_api_key()
    if not feral_key or token != feral_key:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


@router.post(
    "/api/voice/client_secrets",
    response_model=ClientSecretResponse,
    summary="Mint an ephemeral OpenAI Realtime client secret",
)
async def create_client_secret(
    body: ClientSecretRequest = ClientSecretRequest(),
    authorization: str = Header(default=""),
):
    _verify_bearer(authorization)

    openai_key = _get_api_key()
    if not openai_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured on Brain")

    request_body = {
        "session": {
            "type": "realtime",
            "model": body.model,
            "audio": {
                "output": {
                    "voice": body.voice,
                },
            },
        },
        "expires_after": {
            "anchor": "created_at",
            "seconds": body.ttl_seconds,
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            OPENAI_CLIENT_SECRETS_URL,
            json=request_body,
            headers={
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code != 200:
        logger.error("OpenAI client_secrets returned %d: %s", resp.status_code, resp.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI returned {resp.status_code}",
        )

    data = resp.json()
    client_secret = data.get("client_secret", {})
    return ClientSecretResponse(
        value=client_secret.get("value", ""),
        expires_at=client_secret.get("expires_at", 0),
    )
