"""
W16 — per-agent path resolution for the auth profile store.

Mirrors openclaw's ``auth-profiles/path-resolve.ts``: every agent gets
its own subdirectory under ``$FERAL_HOME/agents/<agent_id>/`` so two
agents with disjoint credentials never read each other's secrets even
if one's profile id collides with another's. ``agent_id`` defaults to
``"default"`` — that's the single-agent install everyone has today.

We do NOT use the encrypted vault file (``credentials.enc``) for this
module; auth profiles live in their own JSON files (one per agent).
The vault is the canonical store for the legacy flat-credentials API
and stays untouched by W16 (see :mod:`security.auth_profiles.migrate`
for the read-once import).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from config.loader import feral_home


# Filenames intentionally match openclaw's so future cross-tool diff is
# trivial. ``auth_profiles.json`` is the secret-bearing payload;
# ``auth_state.json`` is reserved for usage/cooldown state once W19
# lands. The legacy flat credentials path is the W9 vault file.
AUTH_PROFILES_FILENAME = "auth_profiles.json"
AUTH_STATE_FILENAME = "auth_state.json"

DEFAULT_AGENT_ID = "default"

# Allowed agent_id alphabet. Filesystem-safe + no path-traversal:
# letters, digits, dash, underscore. Two agents named "twin" and
# "twin/" would otherwise clobber each other on POSIX. Same rule
# openclaw applies via its ``resolveOpenClawAgentDir`` validation.
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def validate_agent_id(agent_id: str) -> str:
    """Normalise + validate an agent id. Returns the cleaned value.

    Raises :class:`ValueError` for empty / non-string / path-hazard
    inputs. We refuse to silently coerce ``"twin/.."`` to ``"twin"``
    because doing so would let a misconfigured caller escape the
    per-agent directory and clobber another agent's profile file.
    """
    if not isinstance(agent_id, str):
        raise ValueError(
            f"agent_id must be a string, got {type(agent_id).__name__}"
        )
    cleaned = agent_id.strip()
    if not cleaned:
        raise ValueError("agent_id must be a non-empty string")
    if not _AGENT_ID_RE.fullmatch(cleaned):
        raise ValueError(
            f"agent_id {agent_id!r} contains characters outside the allowed "
            f"alphabet [A-Za-z0-9_-]; refusing to use it as a directory "
            f"name (path-traversal hazard)."
        )
    return cleaned


def resolve_agent_dir(agent_id: Optional[str] = None) -> Path:
    """Return ``$FERAL_HOME/agents/<agent_id>/`` (does NOT mkdir).

    ``agent_id=None`` falls back to ``DEFAULT_AGENT_ID``. The directory
    is *not* created here; callers that need it materialised should call
    :func:`ensure_agent_dir` so the side effect is explicit.
    """
    cleaned = validate_agent_id(agent_id or DEFAULT_AGENT_ID)
    return feral_home() / "agents" / cleaned


def resolve_auth_profiles_path(agent_id: Optional[str] = None) -> Path:
    """Return the on-disk path for ``<agent>/auth_profiles.json``."""
    return resolve_agent_dir(agent_id) / AUTH_PROFILES_FILENAME


def resolve_auth_state_path(agent_id: Optional[str] = None) -> Path:
    """Return the on-disk path for ``<agent>/auth_state.json`` (reserved
    for the W19 usage/cooldown state machine)."""
    return resolve_agent_dir(agent_id) / AUTH_STATE_FILENAME


def resolve_locks_dir() -> Path:
    """Cross-agent lock directory under ``$FERAL_HOME/locks/``.

    All file locks owned by W16+ live here. The OAuth refresh lock
    creates ``locks/oauth-refresh/`` lazily; other lock families pick
    their own subdirectories.
    """
    return feral_home() / "locks"


def ensure_agent_dir(agent_id: Optional[str] = None) -> Path:
    """Create ``<agent>/`` (chmod 0700) and return its path.

    Idempotent; mkdir uses ``exist_ok=True``. The 0700 chmod is
    advisory — on Windows it's a no-op, on POSIX it keeps the agent
    directory unreadable by other users on the box.
    """
    agent_dir = resolve_agent_dir(agent_id)
    agent_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(agent_dir, 0o700)
    return agent_dir
