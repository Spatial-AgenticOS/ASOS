"""Org reviewer endpoints: queue + approve/reject/quarantine.

All routes here require the reviewer auth dependency (``current_reviewer``)
which checks ``Authorization: Bearer <FERAL_REGISTRY_REVIEWER_SECRET>`` in
constant time. Decisions append to ``review_events`` for an immutable
audit trail; the trail is exposed alongside each queue row so an
operator can see who acted and when without a separate endpoint.

The reviewer scope is intentionally distinct from publisher JWT auth:
publisher tokens cannot moderate, reviewer credentials cannot publish.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Reviewer, current_reviewer
from ..db import get_session
from ..models import (
    ITEM_STATUS_APPROVED,
    ITEM_STATUS_QUARANTINED,
    ITEM_STATUS_REJECTED,
    ITEM_STATUS_SUBMITTED,
    ITEM_STATUSES,
    ITEM_VISIBILITY_PRIVATE,
    ITEM_VISIBILITY_PUBLIC,
    Item,
    Publisher,
    ReviewEvent,
)
from ..schemas import (
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewEventOut,
    ReviewQueueItem,
    ReviewQueueResponse,
)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _load_events(session: AsyncSession, item_id: str) -> list[ReviewEventOut]:
    rows = await session.execute(
        select(ReviewEvent).where(ReviewEvent.item_id == item_id).order_by(ReviewEvent.created_at)
    )
    return [
        ReviewEventOut(
            id=ev.id,
            item_id=ev.item_id,
            event=ev.event,
            actor=ev.actor,
            notes=ev.notes,
            created_at=ev.created_at,
        )
        for ev in rows.scalars().all()
    ]


@router.get("/review/queue", response_model=ReviewQueueResponse)
async def review_queue(
    status_filter: str = Query(default=ITEM_STATUS_SUBMITTED, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    reviewer: Reviewer = Depends(current_reviewer),
) -> ReviewQueueResponse:
    if status_filter != "all" and status_filter not in ITEM_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid status filter")

    base = select(Item, Publisher).join(Publisher, Item.author_id == Publisher.id)
    if status_filter != "all":
        base = base.where(Item.status == status_filter)
    base = base.order_by(desc(Item.created_at))

    total_q = select(func.count()).select_from(base.subquery())
    total = (await session.execute(total_q)).scalar_one()

    rows = (await session.execute(base.limit(limit).offset(offset))).all()

    items: list[ReviewQueueItem] = []
    for item, pub in rows:
        manifest = json.loads(item.manifest_json)
        events = await _load_events(session, item.id)
        items.append(
            ReviewQueueItem(
                id=item.id,
                kind=item.kind,  # type: ignore[arg-type]
                name=item.name,
                version=item.version,
                description=manifest.get("description"),
                publisher=pub.github_login,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
                status=item.status,  # type: ignore[arg-type]
                visibility=item.visibility,  # type: ignore[arg-type]
                reviewed_by=item.reviewed_by,
                reviewed_at=item.reviewed_at,
                review_notes=item.review_notes,
                created_at=item.created_at,
                events=events,
            )
        )
    return ReviewQueueResponse(items=items, total=int(total))


async def _decision(
    session: AsyncSession,
    reviewer: Reviewer,
    item_id: str,
    new_status: Literal["approved", "rejected", "quarantined"],
    new_visibility: Literal["public", "private"],
    notes: str | None,
) -> ReviewActionResponse:
    row = await session.execute(select(Item).where(Item.id == item_id))
    item = row.scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")

    now = _utcnow()
    item.status = new_status
    item.visibility = new_visibility
    item.reviewed_by = reviewer.actor
    item.reviewed_at = now
    if notes is not None:
        item.review_notes = notes

    session.add(
        ReviewEvent(
            item_id=item.id,
            event=new_status,
            actor=reviewer.actor,
            notes=notes,
        )
    )
    await session.commit()
    await session.refresh(item)
    return ReviewActionResponse(
        id=item.id,
        status=item.status,  # type: ignore[arg-type]
        visibility=item.visibility,  # type: ignore[arg-type]
        reviewed_by=item.reviewed_by or reviewer.actor,
        reviewed_at=item.reviewed_at or now,
    )


@router.post("/review/{item_id}/approve", response_model=ReviewActionResponse)
async def approve(
    item_id: str,
    body: ReviewActionRequest | None = None,
    session: AsyncSession = Depends(get_session),
    reviewer: Reviewer = Depends(current_reviewer),
) -> ReviewActionResponse:
    notes = body.notes if body else None
    return await _decision(
        session, reviewer, item_id, ITEM_STATUS_APPROVED, ITEM_VISIBILITY_PUBLIC, notes
    )


@router.post("/review/{item_id}/reject", response_model=ReviewActionResponse)
async def reject(
    item_id: str,
    body: ReviewActionRequest | None = None,
    session: AsyncSession = Depends(get_session),
    reviewer: Reviewer = Depends(current_reviewer),
) -> ReviewActionResponse:
    notes = body.notes if body else None
    return await _decision(
        session, reviewer, item_id, ITEM_STATUS_REJECTED, ITEM_VISIBILITY_PRIVATE, notes
    )


@router.post("/review/{item_id}/quarantine", response_model=ReviewActionResponse)
async def quarantine(
    item_id: str,
    body: ReviewActionRequest | None = None,
    session: AsyncSession = Depends(get_session),
    reviewer: Reviewer = Depends(current_reviewer),
) -> ReviewActionResponse:
    notes = body.notes if body else None
    return await _decision(
        session, reviewer, item_id, ITEM_STATUS_QUARANTINED, ITEM_VISIBILITY_PRIVATE, notes
    )
