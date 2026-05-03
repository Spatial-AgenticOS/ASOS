"""JWT + GitHub OAuth helpers + reviewer auth."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import get_session
from .models import Publisher

GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_USER_URL = "https://api.github.com/user"


def issue_publisher_token(github_login: str, settings: Settings) -> tuple[str, int]:
    ttl = timedelta(days=settings.jwt_ttl_days)
    exp = datetime.now(timezone.utc) + ttl
    payload = {"sub": github_login, "exp": exp}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_publisher_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token payload")
    return sub


async def current_publisher(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Publisher:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    login = decode_publisher_token(token, settings)
    row = await session.execute(select(Publisher).where(Publisher.github_login == login))
    pub = row.scalar_one_or_none()
    if pub is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "publisher not found")
    if pub.blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "publisher is blocked")
    return pub


@dataclass(frozen=True)
class Reviewer:
    """Authenticated org reviewer principal.

    The shared reviewer secret proves org membership; ``actor`` is a
    free-form audit label supplied by the caller via
    ``X-Reviewer-Actor`` header (defaults to ``feral-org`` when absent).
    Once we add GH org OAuth on the website the actor will become the
    reviewer's GitHub login without any API change here.
    """

    actor: str


async def current_reviewer(
    authorization: str | None = Header(default=None),
    x_reviewer_actor: str | None = Header(default=None, alias="X-Reviewer-Actor"),
    settings: Settings = Depends(get_settings),
) -> Reviewer:
    if not settings.reviewer_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "reviewer auth is not configured on this registry",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token, settings.reviewer_secret):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid reviewer credential")
    actor = (x_reviewer_actor or "feral-org").strip()[:200] or "feral-org"
    return Reviewer(actor=f"reviewer:{actor}")


async def optional_reviewer(
    authorization: str | None = Header(default=None),
    x_reviewer_actor: str | None = Header(default=None, alias="X-Reviewer-Actor"),
    settings: Settings = Depends(get_settings),
) -> Reviewer | None:
    """Reviewer dependency that returns ``None`` instead of raising.

    Used by catalog/item/blob endpoints so that an authenticated
    reviewer can see private/non-approved rows while public callers
    keep getting a strict approved+public filter.
    """

    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    if not settings.reviewer_secret:
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token, settings.reviewer_secret):
        return None
    actor = (x_reviewer_actor or "feral-org").strip()[:200] or "feral-org"
    return Reviewer(actor=f"reviewer:{actor}")


async def github_exchange_code(code: str, settings: Settings) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "github did not return access_token")
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        user_resp.raise_for_status()
        return user_resp.json()
