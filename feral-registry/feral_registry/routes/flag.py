"""Community moderation flag endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Flag, Item
from ..schemas import FlagRequest, FlagResponse

router = APIRouter()


@router.post("/flag/{item_id}", response_model=FlagResponse, status_code=status.HTTP_201_CREATED)
async def flag_item(
    item_id: str,
    body: FlagRequest,
    session: AsyncSession = Depends(get_session),
) -> FlagResponse:
    exists = await session.execute(select(Item.id).where(Item.id == item_id))
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")

    flag = Flag(item_id=item_id, reason=body.reason)
    session.add(flag)
    await session.commit()
    await session.refresh(flag)
    return FlagResponse(id=flag.id, item_id=flag.item_id, created_at=flag.created_at)
