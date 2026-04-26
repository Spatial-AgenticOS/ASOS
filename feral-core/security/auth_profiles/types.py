"""
W16 — credential shape definitions for the per-agent auth profile store.

Mirrors openclaw's ``auth-profiles/types.ts`` (`OPENCLAW_LESSONS.md` §1).
A profile is one of three credential shapes:

* :class:`ApiKeyCredential` — the classic provider-issued static key
  (``sk-...``, ``AIza...`` etc.). No refresh lifecycle.
* :class:`OAuthCredential`  — access + refresh token + expiry. The
  refresh token is the precious singleton; consumers must coordinate
  refreshes via :mod:`security.auth_profiles.oauth_refresh_lock` or
  the canonical OAuth provider will revoke the refresh token after a
  reuse-detection event (``refresh_token_reused`` storms; see
  ``OPENCLAW_LESSONS.md`` §1 + §10 W16).
* :class:`TokenCredential` — opaque bearer/PAT-style token with
  optional expiry but **no** locally-known refresh path.

The on-disk JSON layout (one file per agent) is::

    {
      "version": 1,
      "profiles": {
        "openai-default": {
          "type": "api_key",
          "provider": "openai",
          "key": "sk-...",
          ...
        },
        "google-codex:work": {
          "type": "oauth",
          "provider": "google-codex",
          "access": "...",
          "refresh": "...",
          "expires": 1735689600000,
          ...
        }
      },
      "usage_stats": { ... }   # written by usage.py
    }

The shapes are intentionally a flat dataclass — JSON-serialisable via
``asdict``/``from_dict``, no third-party deps. We deliberately avoid
``pydantic`` here because this module is in the security path and must
import cleanly with the smallest possible dependency surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


# Bumping this version invalidates older on-disk payloads. Today there
# is exactly one shape; the field exists so future migrations have a
# clean discriminator.
AUTH_PROFILE_STORE_VERSION = 1

CREDENTIAL_TYPE_API_KEY = "api_key"
CREDENTIAL_TYPE_OAUTH = "oauth"
CREDENTIAL_TYPE_TOKEN = "token"

CREDENTIAL_TYPES: frozenset[str] = frozenset(
    {
        CREDENTIAL_TYPE_API_KEY,
        CREDENTIAL_TYPE_OAUTH,
        CREDENTIAL_TYPE_TOKEN,
    }
)


# ─────────────────────────────────────────────────────────────────────
# Credential shapes
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ApiKeyCredential:
    """Static provider-issued key (e.g. ``sk-...``, ``AIza...``).

    ``key`` is the secret material. ``metadata`` is a freeform
    string-keyed-string map for provider-specific attributes
    (gateway IDs, account IDs, etc.) — never use it for anything that
    needs a refresh lifecycle, because there is no rotation mechanism.
    """

    provider: str
    key: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    metadata: dict[str, str] = field(default_factory=dict)
    type: str = CREDENTIAL_TYPE_API_KEY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OAuthCredential:
    """Refreshable bearer-token credential.

    ``access`` is the short-lived bearer; ``refresh`` is the precious
    long-lived token used to mint new ``access`` values. ``expires`` is
    the unix epoch in **milliseconds** — match openclaw's
    ``OAuthCredentials.expires`` so downstream tooling and the W19
    cooldown FSM can compare timestamps without a unit conversion.

    ``client_id`` is the OAuth app the credential was issued to (NOT a
    secret; identifies the requesting app). ``account_id`` and ``email``
    are identity bindings — they MUST match across mirror/adopt paths
    so we never overwrite one user's profile with another's tokens
    (see openclaw ``isSafeToCopyOAuthIdentity``).
    """

    provider: str
    access: str
    refresh: str
    expires: int
    client_id: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    enterprise_url: Optional[str] = None
    project_id: Optional[str] = None
    account_id: Optional[str] = None
    id_token: Optional[str] = None
    type: str = CREDENTIAL_TYPE_OAUTH

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TokenCredential:
    """Static bearer-style token (PAT or non-refreshable OAuth access).

    Distinct from :class:`OAuthCredential` because there is no refresh
    machinery — when ``expires`` lapses the credential is dead and the
    user must re-issue it manually.
    """

    provider: str
    token: str
    expires: Optional[int] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    type: str = CREDENTIAL_TYPE_TOKEN

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AuthProfileCredential = ApiKeyCredential | OAuthCredential | TokenCredential


def credential_from_dict(payload: dict[str, Any]) -> AuthProfileCredential:
    """Re-hydrate a credential dataclass from on-disk JSON.

    The discriminator is the ``type`` field. Unknown values raise
    :class:`ValueError` — we refuse to silently downgrade a future
    credential shape to whatever today's code understands.
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"credential payload must be a dict, got {type(payload).__name__}"
        )
    raw_type = payload.get("type")
    if raw_type == CREDENTIAL_TYPE_API_KEY:
        return ApiKeyCredential(
            provider=str(payload["provider"]),
            key=str(payload.get("key", "")),
            email=payload.get("email"),
            display_name=payload.get("display_name"),
            metadata={
                str(k): str(v)
                for k, v in (payload.get("metadata") or {}).items()
            },
        )
    if raw_type == CREDENTIAL_TYPE_OAUTH:
        return OAuthCredential(
            provider=str(payload["provider"]),
            access=str(payload.get("access", "")),
            refresh=str(payload.get("refresh", "")),
            expires=int(payload.get("expires", 0) or 0),
            client_id=payload.get("client_id"),
            email=payload.get("email"),
            display_name=payload.get("display_name"),
            enterprise_url=payload.get("enterprise_url"),
            project_id=payload.get("project_id"),
            account_id=payload.get("account_id"),
            id_token=payload.get("id_token"),
        )
    if raw_type == CREDENTIAL_TYPE_TOKEN:
        expires_raw = payload.get("expires")
        return TokenCredential(
            provider=str(payload["provider"]),
            token=str(payload.get("token", "")),
            expires=int(expires_raw) if expires_raw is not None else None,
            email=payload.get("email"),
            display_name=payload.get("display_name"),
        )
    raise ValueError(
        f"unknown credential type {raw_type!r}; expected one of "
        f"{sorted(CREDENTIAL_TYPES)}"
    )


# ─────────────────────────────────────────────────────────────────────
# Per-profile usage stats (placeholder; W19 owns the real cooldown FSM)
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ProfileUsageStats:
    """Minimal usage telemetry per profile.

    ``W19`` will replace the inner book-keeping with a two-lane cooldown
    state machine (cooldown vs disabled, exponential backoff, per-model
    scope). For W16 we only persist the three counters that prove the
    file format is forward-compatible: success/failure totals and the
    last-used timestamp (unix epoch milliseconds).

    See ``OPENCLAW_LESSONS.md`` §10 W19 for the canonical FSM contract.
    """

    success_count: int = 0
    failure_count: int = 0
    last_used_at: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProfileUsageStats":
        if not isinstance(payload, dict):
            return cls()
        last_used = payload.get("last_used_at")
        return cls(
            success_count=int(payload.get("success_count", 0) or 0),
            failure_count=int(payload.get("failure_count", 0) or 0),
            last_used_at=int(last_used) if last_used is not None else None,
        )


# ─────────────────────────────────────────────────────────────────────
# Storage protocol
# ─────────────────────────────────────────────────────────────────────


@runtime_checkable
class AuthProfileStore(Protocol):
    """Minimum surface a per-agent auth profile store must expose.

    The concrete implementation lives in :mod:`security.auth_profiles.store`.
    Tests can substitute an in-memory fake by implementing the same
    methods — that's why this is a :class:`Protocol` and not an ABC.
    """

    agent_id: str

    def load(self) -> dict[str, AuthProfileCredential]:
        ...

    def get(self, profile_id: str) -> Optional[AuthProfileCredential]:
        ...

    def upsert(self, profile_id: str, credential: AuthProfileCredential) -> None:
        ...

    def delete(self, profile_id: str) -> bool:
        ...

    def list_profiles(self) -> list[str]:
        ...

    def usage(self, profile_id: str) -> ProfileUsageStats:
        ...
