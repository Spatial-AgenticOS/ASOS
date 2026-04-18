"""GitHub OAuth login/callback and publisher pubkey registration."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    GITHUB_AUTHORIZE_URL,
    current_publisher,
    github_exchange_code,
    issue_publisher_token,
)
from ..config import Settings, get_settings
from ..db import get_session
from ..models import Publisher
from ..schemas import (
    AuthTokenResponse,
    PubkeyRegisterRequest,
    PubkeyRegisterResponse,
)

router = APIRouter()


def _require_github_configured(settings: Settings) -> None:
    if not settings.github_configured:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "not configured")


@router.get("/auth/github/login")
async def github_login(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    _require_github_configured(settings)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "read:user",
        "allow_signup": "true",
    }
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/auth/github/callback", response_model=AuthTokenResponse)
async def github_callback(
    code: str = Query(...),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthTokenResponse:
    _require_github_configured(settings)
    user = await github_exchange_code(code, settings)
    login = str(user.get("login", "")).strip()
    gh_id = user.get("id")
    if not login or not isinstance(gh_id, int):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "github user payload missing fields")

    row = await session.execute(select(Publisher).where(Publisher.github_login == login))
    pub = row.scalar_one_or_none()
    if pub is None:
        pub = Publisher(github_login=login, github_id=gh_id)
        session.add(pub)
    else:
        pub.github_id = gh_id
    await session.commit()

    token, ttl = issue_publisher_token(login, settings)
    return AuthTokenResponse(access_token=token, github_login=login, expires_in=ttl)


@router.post("/auth/github/register_pubkey", response_model=PubkeyRegisterResponse)
async def register_pubkey(
    body: PubkeyRegisterRequest,
    publisher: Publisher = Depends(current_publisher),
    session: AsyncSession = Depends(get_session),
) -> PubkeyRegisterResponse:
    publisher.pubkey_hex = body.pubkey_hex.lower()
    await session.commit()
    return PubkeyRegisterResponse(
        github_login=publisher.github_login,
        pubkey_hex=publisher.pubkey_hex,
    )
