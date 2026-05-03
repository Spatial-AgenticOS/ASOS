"""Pydantic request/response schemas.

The registry hosts nine content categories. Each is a ``kind`` in the
``items`` table; publishers upload a tarball with a ``manifest.json`` at
the root, and the ``Manifest`` model below accepts any of the nine
discriminated shapes. Categories:

* ``skill``     — Python skill (manifest + impl.py) loaded into the
                  SkillRegistry on the user's FERAL brain.
* ``app``       — GenUI third-party app (AppManifest + brand + surfaces
                  + interaction rules). Installs into AppRegistry;
                  renders on v2 via SduiRenderer. See
                  feral-core/models/app_manifest.py.
* ``daemon``    — HUP-speaking hardware daemon, one per physical device
                  class (wristband, glasses, thermostat, …).
* ``mcp``       — MCP server spec (command + env) that FERAL can spawn
                  and talk to over stdio or SSE.
* ``channel``   — Messaging-channel plugin (Telegram/Discord variants,
                  WhatsApp, Signal, Matrix, etc.) that plugs into the
                  ChannelManager.
* ``provider``  — Alternative LLM provider adapter (Groq, Bedrock,
                  Ollama, Together, Anthropic, …) plugged in behind the
                  stable provider contract.
* ``memory``    — Memory-backend implementation. Exactly one active at a
                  time per brain (numpy fallback, sqlite-vec, Chroma,
                  Qdrant, Honcho…).
* ``workflow``  — Named multi-step procedure the agent can invoke ("PR
                  triage", "Daily standup composer", …) — a structured
                  TaskFlow template.
* ``agent``     — Specialist persona: system prompt + tool permission
                  list an AgentMitosisEngine can spawn on demand.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal[
    "skill",
    "app",
    "daemon",
    "mcp",
    "channel",
    "provider",
    "memory",
    "workflow",
    "agent",
]

ALL_KINDS: tuple[Kind, ...] = (
    "skill",
    "app",
    "daemon",
    "mcp",
    "channel",
    "provider",
    "memory",
    "workflow",
    "agent",
)


class Manifest(BaseModel):
    """Common fields every kind's manifest must carry.

    Per-kind extensions (channel_id, provider_id, mcp_command, etc.) are
    accepted via ``extra='allow'``. Validators elsewhere enforce the
    per-kind required keys — see :func:`validate_manifest_for_kind`.
    """

    model_config = ConfigDict(extra="allow")

    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    description: str | None = None
    author: str | None = None


_REQUIRED_PER_KIND: dict[str, tuple[str, ...]] = {
    # kind: keys that must be present in the manifest on top of the base fields
    "skill": ("skill_id",),
    # GenUI app bundles must declare a valid app_id, a brand, an entry
    # surface, and at least one surface. Deeper cross-ref checks run
    # in feral-core's AppManifest validator; the registry only guards
    # against the top-level shape here so an obviously-broken bundle
    # can't reach a blob lock.
    "app": ("app_id", "brand", "entry_surface_id", "surfaces"),
    "daemon": ("node_id", "capabilities"),
    "mcp": ("mcp_command",),
    "channel": ("channel_id",),
    "provider": ("provider_id", "models"),
    "memory": ("memory_id", "interface"),
    "workflow": ("steps",),
    "agent": ("system_prompt",),
}


def validate_manifest_for_kind(manifest: Manifest) -> list[str]:
    """Return a list of missing required keys for the declared kind.

    Used by /publish to reject malformed bundles before we take a blob
    lock. Empty list means the manifest is conformant.
    """
    required = _REQUIRED_PER_KIND.get(manifest.kind, ())
    raw = manifest.model_dump()
    return [key for key in required if key not in raw or raw[key] in (None, "", [], {})]


ItemStatus = Literal["submitted", "approved", "rejected", "quarantined"]
Visibility = Literal["private", "public"]


class PublishResponse(BaseModel):
    id: str
    sha256: str
    download_url: str
    verified: bool
    status: ItemStatus = "submitted"
    visibility: Visibility = "private"
    message: str = (
        "submission received, pending review by FERAL org reviewers; "
        "this item is not user-installable until approved"
    )


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
    status: ItemStatus = "approved"
    visibility: Visibility = "public"


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
    status: ItemStatus = "approved"
    visibility: Visibility = "public"


class ReviewEventOut(BaseModel):
    id: str
    item_id: str
    event: str
    actor: str
    notes: str | None
    created_at: datetime


class ReviewQueueItem(BaseModel):
    id: str
    kind: Kind
    name: str
    version: str
    description: str | None = None
    publisher: str
    sha256: str
    size_bytes: int
    status: ItemStatus
    visibility: Visibility
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime
    events: list[ReviewEventOut]


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    total: int


class ReviewActionRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


class ReviewActionResponse(BaseModel):
    id: str
    status: ItemStatus
    visibility: Visibility
    reviewed_by: str
    reviewed_at: datetime


class PublisherSubmissionItem(BaseModel):
    id: str
    kind: Kind
    name: str
    version: str
    sha256: str
    status: ItemStatus
    visibility: Visibility
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime


class PublisherSubmissionsResponse(BaseModel):
    publisher: str
    items: list[PublisherSubmissionItem]
    total: int


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
