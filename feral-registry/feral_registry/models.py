"""SQLAlchemy models: publishers, items, flags, review events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Item moderation lifecycle. New submissions land in `submitted` and are
# private; reviewers move them to `approved` (public) or `rejected` /
# `quarantined` (private). Visibility is tracked separately so a reviewer
# can stage an approved-but-not-yet-public item if needed.
ITEM_STATUS_SUBMITTED = "submitted"
ITEM_STATUS_APPROVED = "approved"
ITEM_STATUS_REJECTED = "rejected"
ITEM_STATUS_QUARANTINED = "quarantined"
ITEM_STATUSES = (
    ITEM_STATUS_SUBMITTED,
    ITEM_STATUS_APPROVED,
    ITEM_STATUS_REJECTED,
    ITEM_STATUS_QUARANTINED,
)

ITEM_VISIBILITY_PRIVATE = "private"
ITEM_VISIBILITY_PUBLIC = "public"
ITEM_VISIBILITIES = (ITEM_VISIBILITY_PRIVATE, ITEM_VISIBILITY_PUBLIC)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    github_login: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    github_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pubkey_hex: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    items: Mapped[list["Item"]] = relationship(back_populates="author")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("kind", "name", "version", name="uq_items_kind_name_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # skill|daemon|mcp
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("publishers.id"), nullable=False, index=True)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    blob_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    signature_b64: Mapped[str] = mapped_column(Text, nullable=False)
    downloads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ITEM_STATUS_SUBMITTED, index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ITEM_VISIBILITY_PRIVATE, index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    author: Mapped[Publisher] = relationship(back_populates="items")
    flags: Mapped[list["Flag"]] = relationship(back_populates="item")
    review_events: Mapped[list["ReviewEvent"]] = relationship(
        back_populates="item", order_by="ReviewEvent.created_at"
    )


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    item: Mapped[Item] = relationship(back_populates="flags")


class ReviewEvent(Base):
    """Immutable moderation audit trail.

    Each lifecycle transition (publish_received, approved, rejected,
    quarantined, restored) writes one row. ``actor`` is a free-form
    string of the form ``publisher:<github_login>`` for self-events and
    ``reviewer:<id>`` for org-side decisions. Rows are append-only by
    convention; downgrade tooling drops the table but no app code
    mutates existing rows.
    """

    __tablename__ = "review_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    item: Mapped[Item] = relationship(back_populates="review_events")
