"""Catalog listing with filtering and simple sorting."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Item, Publisher
from ..schemas import CatalogItem, CatalogResponse, Kind

router = APIRouter()


@router.get("/catalog", response_model=CatalogResponse)
async def catalog(
    kind: Kind | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: Literal["newest", "popular"] = Query(default="newest"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> CatalogResponse:
    base = select(Item, Publisher).join(Publisher, Item.author_id == Publisher.id)

    if kind is not None:
        base = base.where(Item.kind == kind)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(
            or_(
                func.lower(Item.name).like(like),
                func.lower(Item.manifest_json).like(like),
            )
        )

    if sort == "popular":
        base = base.order_by(desc(Item.downloads), desc(Item.created_at))
    else:
        base = base.order_by(desc(Item.created_at))

    total_q = select(func.count()).select_from(base.subquery())
    total = (await session.execute(total_q)).scalar_one()

    rows = (await session.execute(base.limit(limit).offset(offset))).all()

    results: list[CatalogItem] = []
    for item, pub in rows:
        manifest = json.loads(item.manifest_json)
        results.append(
            CatalogItem(
                id=item.id,
                kind=item.kind,  # type: ignore[arg-type]
                name=item.name,
                version=item.version,
                description=manifest.get("description"),
                publisher=pub.github_login,
                downloads=item.downloads,
                verified=item.verified,
                created_at=item.created_at,
            )
        )
    return CatalogResponse(items=results, total=int(total))
