"""Serve stored bundle blobs by sha256 digest."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_session
from ..models import Item

router = APIRouter()


@router.get("/blobs/{sha256}")
async def get_blob(
    sha256: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256.lower()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid sha256")

    row = await session.execute(select(Item).where(Item.sha256 == sha256))
    item = row.scalars().first()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blob not found")

    path = Path(item.blob_path)
    if not path.exists():
        # Fall back to the conventional layout under the configured blob dir.
        path = settings.blob_dir / f"{sha256}.tar.gz"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blob missing on disk")

    await session.execute(
        update(Item).where(Item.id == item.id).values(downloads=Item.downloads + 1)
    )
    await session.commit()

    return FileResponse(
        path=path,
        media_type="application/gzip",
        filename=f"{item.name}-{item.version}.tar.gz",
    )
