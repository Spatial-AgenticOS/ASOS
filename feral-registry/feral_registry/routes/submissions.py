"""Publisher self-service: list submissions and their review state.

Publishers authenticate with their normal JWT bearer token and see
*only their own* items, including the ones still in the review queue
or rejected. This is what powers the ``/publisher/submissions`` page
on feral.sh so publishers can see review status without needing
reviewer credentials.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_publisher
from ..db import get_session
from ..models import Item, Publisher
from ..schemas import PublisherSubmissionItem, PublisherSubmissionsResponse

router = APIRouter()


@router.get("/publisher/submissions", response_model=PublisherSubmissionsResponse)
async def list_submissions(
    publisher: Publisher = Depends(current_publisher),
    session: AsyncSession = Depends(get_session),
) -> PublisherSubmissionsResponse:
    base = (
        select(Item)
        .where(Item.author_id == publisher.id)
        .order_by(desc(Item.created_at))
    )
    rows = (await session.execute(base)).scalars().all()
    total = (
        await session.execute(
            select(func.count()).select_from(
                select(Item).where(Item.author_id == publisher.id).subquery()
            )
        )
    ).scalar_one()

    items = [
        PublisherSubmissionItem(
            id=row.id,
            kind=row.kind,  # type: ignore[arg-type]
            name=row.name,
            version=row.version,
            sha256=row.sha256,
            status=row.status,  # type: ignore[arg-type]
            visibility=row.visibility,  # type: ignore[arg-type]
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            review_notes=row.review_notes,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return PublisherSubmissionsResponse(
        publisher=publisher.github_login,
        items=items,
        total=int(total),
    )
