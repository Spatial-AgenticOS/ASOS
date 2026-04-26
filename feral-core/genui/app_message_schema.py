"""Strict postMessage schema for AppSurface iframe → host messages.

The AppSurface iframe sandbox (see roadmap §3.3 #2) lets the GenUI
surface emit ``postMessage`` events to its parent (FERAL host page).
Without a tight schema, a compromised app could spam the host with
arbitrary objects and hope something slips through into FERAL's own
handlers.

We pin three things here:

* The message envelope (:class:`AppMessage`) — strict pydantic v2
  model, ``extra="forbid"`` so unexpected fields are rejected before
  the message ever reaches FERAL's reducer.
* The enum of allowed ``type`` values (:class:`AppMessageType`).
  Anything outside this enum is dropped.
* The maximum payload size (:data:`MAX_PAYLOAD_BYTES`). 64 KiB matches
  the upper bound the brain's ui_event hot path is willing to accept;
  anything larger is denied here so the iframe can't DoS the host
  channel.

The TypeScript mirror at ``feral-client-v2/src/pages/AppSurface.types.ts``
must stay in lockstep — there's a comment in both files reminding
maintainers to update both halves together. The Python side is the
authoritative schema for backend parsers (registry / brain replay);
the TS side is what the host actually runs to drop malformed events
before dispatch.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


__all__ = [
    "AppMessage",
    "AppMessageType",
    "AppMessageError",
    "MAX_PAYLOAD_BYTES",
    "validate_app_message",
]


MAX_PAYLOAD_BYTES = 64 * 1024  # 64 KiB hard cap — see module docstring.


class AppMessageType(str, Enum):
    """Allowed AppMessage types. Add cases here, never inline literals."""

    REQUEST_DATA = "request_data"
    SUBMIT_FORM = "submit_form"
    NAVIGATE = "navigate"
    CLOSE = "close"


class AppMessageError(ValueError):
    """Raised by :func:`validate_app_message` for any malformed input."""


class AppMessage(BaseModel):
    """The strict envelope for app→host postMessage events.

    Fields:
      * ``type`` — one of :class:`AppMessageType`. ``Literal`` would be
        sufficient too, but the enum lets the TS mirror import the
        same names symbolically.
      * ``payload`` — opaque dict. We don't attempt schema-level
        validation of payload contents here — that's the host's job
        per message type. We do enforce the *size* of the payload.
      * ``message_id`` — caller-supplied correlation id. Required so
        the host can ack/reject specific messages without ambiguity.
      * ``signed_with_key_id`` — the publisher key id whose Ed25519
        signature gated the install. We carry it on every message so
        the host can verify the iframe wasn't swapped at runtime.

    Pydantic v2 ``extra="forbid"`` means an attacker can't smuggle in
    side-channel fields hoping the host might forward them.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    type: AppMessageType = Field(
        ...,
        description="Allowed message kind; see AppMessageType.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-type opaque payload. Size-capped by the validator.",
    )
    message_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Caller-correlation id; the host echoes this in acks.",
    )
    signed_with_key_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Key id from the SignedManifest that gated install.",
    )

    @field_validator("payload")
    @classmethod
    def _payload_within_bounds(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("payload must be a dict")
        try:
            blob = json.dumps(v, default=str).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload must be JSON-serialisable: {exc}") from exc
        if len(blob) > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"payload too large: {len(blob)} bytes "
                f"(max {MAX_PAYLOAD_BYTES})"
            )
        return v


def validate_app_message(raw: Any) -> Optional[AppMessage]:
    """Best-effort validation that NEVER raises.

    Mirrors the host-side TS guard: returns ``None`` for any malformed
    input, so the host can drop the event silently without crashing
    its message loop. Callers that need the failure reason can call
    :class:`AppMessage` directly and catch ``ValidationError``.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return AppMessage.model_validate(raw)
    except ValidationError:
        return None
    except Exception:  # pragma: no cover — pydantic only raises ValidationError
        return None
