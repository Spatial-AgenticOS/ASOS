"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["skill", "daemon", "mcp"]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    description: str | None = None
    author: str | None = None


class PublishResponse(BaseModel):
    id: str
    sha256: str
    download_url: str
    verified: bool


class CatalogItem(BaseModel):
    id: str
    kind: Kind
    name: str
    version: str
    description: str | None = None
    publisher: str
    downloads: int
    verified: bool
    created_at: datetime


class CatalogResponse(BaseModel):
    items: list[CatalogItem]
    total: int


class ItemDetail(BaseModel):
    id: str
    kind: Kind
    name: str
    version: str
    manifest: dict[str, Any]
    publisher: str
    publisher_pubkey: str | None
    sha256: str
    size_bytes: int
    signature_b64: str
    download_url: str
    downloads: int
    verified: bool
    created_at: datetime


class FlagRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class FlagResponse(BaseModel):
    id: str
    item_id: str
    created_at: datetime


class PubkeyRegisterRequest(BaseModel):
    pubkey_hex: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class PubkeyRegisterResponse(BaseModel):
    github_login: str
    pubkey_hex: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    github_login: str
    expires_in: int


class HealthResponse(BaseModel):
    status: str
    version: str


class ErrorResponse(BaseModel):
    detail: str
