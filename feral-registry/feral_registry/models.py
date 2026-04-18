"""SQLAlchemy models: publishers, items, flags."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


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

    author: Mapped[Publisher] = relationship(back_populates="items")
    flags: Mapped[list["Flag"]] = relationship(back_populates="item")


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    item: Mapped[Item] = relationship(back_populates="flags")
