"""
W16 — read-once import of the legacy ``credentials.json`` blob into the
new per-agent auth profile store.

Why a separate module instead of editing :mod:`security.vault`?
``vault.py`` is the W9 encrypted-at-rest vault and is owned by W9. W16
is additive: we read the *legacy plaintext* file once, classify each
value as either an :class:`OAuthCredential` (when it's a dict
containing ``refresh_token``) or an :class:`ApiKeyCredential` (when it's
a bare string), write the result to the per-agent file, back the legacy
file up to ``credentials.json.bak.legacy.w16`` (mode 0600), and stop.
W9 still owns the eventual deletion of the original file.

Idempotence:
    First call: legacy file present + per-agent file absent → migrates,
    creates backup, logs an info line.
    Subsequent calls (per-agent file present): no-op, returns 0.
    First call when legacy file absent: no-op, returns 0.

The migration is intentionally not wired into vault import time —
calling it eagerly would break the W9 vault tests. Callers that want
the migration to happen at brain boot must invoke
:func:`run_migration_if_needed` from their startup path. Today the only
two callers are :func:`feral key migrate` (manual trigger) and the
boot path follow-up tracked in
``docs/AGENT_PROMPTS_FOLLOWUPS.md``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.loader import feral_home

from .paths import (
    DEFAULT_AGENT_ID,
    ensure_agent_dir,
    resolve_auth_profiles_path,
    validate_agent_id,
)
from .store import AuthProfileFileStore
from .types import (
    ApiKeyCredential,
    AuthProfileCredential,
    OAuthCredential,
)


logger = logging.getLogger("feral.auth_profiles.migrate")


# Filename intentionally distinct from W9's ``credentials.json.bak.legacy``
# so the two backups never collide. The trailing ``.w16`` documents which
# workstream owns the file when an operator inspects the directory.
LEGACY_BACKUP_SUFFIX = ".bak.legacy.w16"


@dataclass(frozen=True)
class MigrationResult:
    """Summary returned by :func:`run_migration_if_needed`.

    ``migrated``       — True when this call wrote new files.
    ``entries``        — count of credentials written into the per-agent file.
    ``api_keys``       — subset of ``entries`` classified as API keys.
    ``oauth``          — subset of ``entries`` classified as OAuth blobs.
    ``backup_path``    — where the legacy file was copied (if migrated).
    ``legacy_path``    — the legacy plaintext file path we read from.
    ``destination``    — the per-agent ``auth_profiles.json`` we wrote.
    ``noop_reason``    — present when ``migrated=False``; one of
                         ``"already-migrated"``, ``"no-legacy-file"``.
    """

    migrated: bool
    entries: int
    api_keys: int
    oauth: int
    backup_path: Optional[Path]
    legacy_path: Path
    destination: Path
    noop_reason: Optional[str] = None


def _legacy_credentials_path() -> Path:
    """Path of the legacy pre-W9 plaintext credentials file."""
    return feral_home() / "credentials.json"


def _classify(value: object, *, key: str) -> AuthProfileCredential:
    """Map one legacy ``{key: value}`` entry to a credential dataclass.

    Heuristic, mirrored from openclaw's ``applyLegacyAuthStore``:

    * a ``dict`` containing ``refresh_token`` → :class:`OAuthCredential`
      (provider derived from the key prefix; access/expires copied
      verbatim if present).
    * a non-empty string → :class:`ApiKeyCredential` (provider derived
      from the key, the entire string is the secret).
    * anything else → :class:`ValueError` (we never silently drop
      credentials, even malformed ones — operators must see the
      problem and fix it).

    The legacy ``credentials.json`` had no provider discriminator
    inside the value, so we derive ``provider`` from the entry key:
    ``openai_api_key`` → ``openai``, ``anthropic`` → ``anthropic`` etc.
    The exact rule is a strip of the trailing ``_api_key`` /
    ``_token`` / ``_oauth`` suffix so the most common naming
    conventions (``openai_api_key``, ``slack_token``, ``google_oauth``)
    all collapse to a clean provider id.
    """
    provider = _provider_from_key(key)
    if isinstance(value, dict):
        if "refresh_token" not in value:
            raise ValueError(
                f"legacy credential {key!r} is a dict without "
                f"'refresh_token'; cannot classify as OAuth or API key. "
                f"Inspect the legacy file and migrate manually."
            )
        return OAuthCredential(
            provider=str(value.get("provider") or provider),
            access=str(value.get("access_token") or value.get("access") or ""),
            refresh=str(value["refresh_token"]),
            expires=int(value.get("expires") or value.get("expires_at") or 0),
            client_id=value.get("client_id"),
            email=value.get("email"),
            display_name=value.get("display_name"),
            account_id=value.get("account_id"),
            id_token=value.get("id_token"),
        )
    if isinstance(value, str):
        if not value:
            raise ValueError(
                f"legacy credential {key!r} is an empty string; "
                f"refusing to migrate an empty key."
            )
        return ApiKeyCredential(provider=provider, key=value)
    raise ValueError(
        f"legacy credential {key!r} has unsupported type "
        f"{type(value).__name__}; expected dict (OAuth) or str (API key)."
    )


def _provider_from_key(key: str) -> str:
    """Derive a provider id from a legacy credential key.

    Strips the most common suffixes so ``openai_api_key`` becomes
    ``openai``. Falls back to the original key if no suffix matches —
    we never invent a provider name.
    """
    lowered = key.strip().lower()
    for suffix in ("_api_key", "_apikey", "_token", "_oauth", "_credential"):
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def run_migration_if_needed(
    *,
    agent_id: str = DEFAULT_AGENT_ID,
) -> MigrationResult:
    """Idempotent migration of the legacy flat credentials file.

    Returns a :class:`MigrationResult` describing what happened. Never
    raises for the "no legacy file" or "already migrated" cases — those
    are normal and surface as ``migrated=False`` with a populated
    ``noop_reason``. A malformed legacy file *does* raise, because we
    never want to silently drop credentials.
    """
    cleaned_agent = validate_agent_id(agent_id)
    legacy_path = _legacy_credentials_path()
    destination = resolve_auth_profiles_path(cleaned_agent)

    if destination.exists():
        return MigrationResult(
            migrated=False,
            entries=0,
            api_keys=0,
            oauth=0,
            backup_path=None,
            legacy_path=legacy_path,
            destination=destination,
            noop_reason="already-migrated",
        )

    if not legacy_path.exists():
        return MigrationResult(
            migrated=False,
            entries=0,
            api_keys=0,
            oauth=0,
            backup_path=None,
            legacy_path=legacy_path,
            destination=destination,
            noop_reason="no-legacy-file",
        )

    raw = legacy_path.read_text(encoding="utf-8")
    parsed = json.loads(raw) if raw.strip() else {}
    if not isinstance(parsed, dict):
        raise ValueError(
            f"legacy credentials file {legacy_path} is not a JSON object "
            f"(got {type(parsed).__name__}); refusing to migrate."
        )

    ensure_agent_dir(cleaned_agent)
    store = AuthProfileFileStore(cleaned_agent)

    api_keys = 0
    oauth = 0

    def _do_migrate(profiles: dict[str, AuthProfileCredential]) -> bool:
        nonlocal api_keys, oauth
        for key, value in parsed.items():
            credential = _classify(value, key=str(key))
            profiles[str(key)] = credential
            if credential.type == "oauth":
                oauth += 1
            else:
                api_keys += 1
        return True

    store.update_with_lock(_do_migrate)

    backup_path = legacy_path.with_name(legacy_path.name + LEGACY_BACKUP_SUFFIX)
    shutil.copy2(legacy_path, backup_path)
    if os.name == "posix":
        os.chmod(backup_path, 0o600)

    entries = api_keys + oauth
    logger.info(
        "auth_profiles.migrated_from_legacy: %d entries to %s agent",
        entries, cleaned_agent,
    )

    return MigrationResult(
        migrated=True,
        entries=entries,
        api_keys=api_keys,
        oauth=oauth,
        backup_path=backup_path,
        legacy_path=legacy_path,
        destination=destination,
    )
