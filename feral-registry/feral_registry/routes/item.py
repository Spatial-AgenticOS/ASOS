"""Item detail endpoint."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_session
from ..models import Item, Publisher
from ..schemas import ItemDetail

router = APIRouter()


@router.get("/item/{item_id}", response_model=ItemDetail)
async def get_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ItemDetail:
    row = await session.execute(
        select(Item, Publisher).join(Publisher, Item.author_id == Publisher.id).where(Item.id == item_id)
    )
    result = row.first()
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    item, publisher = result
    return ItemDetail(
        id=item.id,
        kind=item.kind,  # type: ignore[arg-type]
        name=item.name,
        version=item.version,
        manifest=json.loads(item.manifest_json),
        publisher=publisher.github_login,
        publisher_pubkey=publisher.pubkey_hex,
        sha256=item.sha256,
        size_bytes=item.size_bytes,
        signature_b64=item.signature_b64,
        download_url=f"{settings.public_base_url}/blobs/{item.sha256}",
        downloads=item.downloads,
        verified=item.verified,
        created_at=item.created_at,
    )
