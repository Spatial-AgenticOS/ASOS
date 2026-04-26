"""
W16 — per-agent auth profile file store.

On-disk authority. One JSON file per agent at
``$FERAL_HOME/agents/<agent_id>/auth_profiles.json``. Mirrors openclaw's
``auth-profiles/store.ts`` minus the runtime-snapshot cache (FERAL is
single-process today; there is no gateway daemon racing against the
CLI). The atomic-update path uses the same OS file lock as openclaw's
``withFileLock`` so a future multi-process FERAL deployment is safe by
construction.

Concurrency model:

* Reads (:meth:`AuthProfileFileStore.load`, :meth:`get`,
  :meth:`list_profiles`) take **no** lock — the file is parsed under
  whatever the kernel hands us; a torn write would surface as a JSON
  decode error which we re-raise (no swallowed exceptions).
* Writes (:meth:`upsert`, :meth:`delete`, :meth:`update_usage`) take an
  **exclusive** ``fcntl.flock`` on a ``.lock`` sidecar file under
  :func:`security.auth_profiles.paths.resolve_locks_dir`. The write is
  staged to ``auth_profiles.json.new`` then renamed atomically
  (``os.replace``) so a crashed writer never leaves a partially-written
  authoritative file.
* :meth:`with_lock` exposes the same lock as a context manager so
  callers that need a read-modify-write sequence (e.g. mirror an
  OAuth refresh into the store) can serialize against concurrent
  writers without re-implementing the lock dance.

The store is **encrypted-at-rest only via filesystem permissions**
(chmod 0600 on the file, 0700 on the directory). Secret material is
unencrypted JSON inside the file — we do NOT reuse the W9 vault's
ChaCha20-Poly1305 because (a) the vault is a single flat namespace
and W16's contract is many per-agent files, and (b) entangling the
two stores would force every per-agent write through the vault's
keychain dependency.

Threat model: a process running as the FERAL user can read these files;
a process running as another user cannot (chmod 0600). Same posture as
the legacy ``credentials.json`` had pre-W9. Disk-encryption is the
operator's responsibility; the W9 vault remains the authority for the
flat credentials namespace.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Callable, Iterator, Optional

from .paths import (
    DEFAULT_AGENT_ID,
    ensure_agent_dir,
    resolve_auth_profiles_path,
    resolve_locks_dir,
    validate_agent_id,
)
from .types import (
    AUTH_PROFILE_STORE_VERSION,
    AuthProfileCredential,
    ProfileUsageStats,
    credential_from_dict,
)


logger = logging.getLogger("feral.auth_profiles.store")


_PROFILES_KEY = "profiles"
_VERSION_KEY = "version"
_USAGE_KEY = "usage_stats"


class AuthProfileFileStore:
    """Per-agent JSON-on-disk auth profile store.

    Construct one instance per ``agent_id``. The store is cheap to
    construct (no I/O until the first :meth:`load`) so the recommended
    pattern is to instantiate per-request rather than caching globally.
    """

    def __init__(self, agent_id: Optional[str] = None) -> None:
        # Use ``is None`` rather than truthiness so an explicitly-empty
        # string ("") surfaces as a ValueError (path-traversal hazard)
        # instead of silently becoming the default agent.
        if agent_id is None:
            self.agent_id = DEFAULT_AGENT_ID
        else:
            self.agent_id = validate_agent_id(agent_id)
        self._path = resolve_auth_profiles_path(self.agent_id)

    # ── Paths ──────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    @property
    def lock_path(self) -> Path:
        return resolve_locks_dir() / "auth-profiles" / f"{self.agent_id}.lock"

    # ── Read ───────────────────────────────────────────────────────

    def _read_payload(self) -> dict:
        if not self._path.exists():
            return {
                _VERSION_KEY: AUTH_PROFILE_STORE_VERSION,
                _PROFILES_KEY: {},
                _USAGE_KEY: {},
            }
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return {
                _VERSION_KEY: AUTH_PROFILE_STORE_VERSION,
                _PROFILES_KEY: {},
                _USAGE_KEY: {},
            }
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"auth_profiles file {self._path} is not a JSON object "
                f"(got {type(parsed).__name__}); refusing to use it."
            )
        version = parsed.get(_VERSION_KEY)
        if version is not None and version != AUTH_PROFILE_STORE_VERSION:
            raise ValueError(
                f"auth_profiles file {self._path} has unknown version "
                f"{version!r}; this build only understands "
                f"{AUTH_PROFILE_STORE_VERSION}. Upgrade FERAL or rotate "
                f"the file out of the way."
            )
        parsed.setdefault(_VERSION_KEY, AUTH_PROFILE_STORE_VERSION)
        parsed.setdefault(_PROFILES_KEY, {})
        parsed.setdefault(_USAGE_KEY, {})
        if not isinstance(parsed[_PROFILES_KEY], dict):
            raise ValueError(
                f"auth_profiles file {self._path} has non-dict 'profiles' "
                f"section ({type(parsed[_PROFILES_KEY]).__name__}); "
                f"refusing to use it."
            )
        if not isinstance(parsed[_USAGE_KEY], dict):
            raise ValueError(
                f"auth_profiles file {self._path} has non-dict 'usage_stats' "
                f"section ({type(parsed[_USAGE_KEY]).__name__}); "
                f"refusing to use it."
            )
        return parsed

    def load(self) -> dict[str, AuthProfileCredential]:
        """Return ``{profile_id: credential}`` from disk (no lock).

        An absent file is treated as an empty store. A malformed file
        raises :class:`ValueError` — we never silently drop credentials.
        """
        payload = self._read_payload()
        return {
            str(profile_id): credential_from_dict(raw)
            for profile_id, raw in payload[_PROFILES_KEY].items()
        }

    def get(self, profile_id: str) -> Optional[AuthProfileCredential]:
        """Return one credential or ``None`` if missing."""
        return self.load().get(profile_id)

    def list_profiles(self) -> list[str]:
        """Return all profile ids known to this agent (sorted)."""
        return sorted(self.load().keys())

    def usage(self, profile_id: str) -> ProfileUsageStats:
        payload = self._read_payload()
        raw = payload[_USAGE_KEY].get(profile_id)
        if raw is None:
            return ProfileUsageStats()
        return ProfileUsageStats.from_dict(raw)

    # ── Write (lock-guarded, atomic) ───────────────────────────────

    @contextlib.contextmanager
    def with_lock(self) -> Iterator[None]:
        """Hold the per-agent write lock.

        On POSIX this is a real ``fcntl.flock``. On non-POSIX hosts we
        fall back to a directory-creation marker that's *not* truly
        atomic across processes — Windows multi-process auth-profile
        editing is not a supported scenario and we'd rather a future
        Windows port surface as a clear failure than silently corrupt
        the file.
        """
        if os.name != "posix":
            ensure_agent_dir(self.agent_id)
            yield
            return

        import fcntl

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _atomic_write(self, payload: dict) -> None:
        ensure_agent_dir(self.agent_id)
        tmp = self._path.with_name(self._path.name + ".new")
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        with open(tmp, "wb") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)
        if os.name == "posix":
            os.chmod(self._path, 0o600)

    def upsert(
        self, profile_id: str, credential: AuthProfileCredential
    ) -> None:
        """Insert or replace a single profile, atomic + locked."""
        if not profile_id or not isinstance(profile_id, str):
            raise ValueError("profile_id must be a non-empty string")
        with self.with_lock():
            payload = self._read_payload()
            payload[_PROFILES_KEY][profile_id] = credential.to_dict()
            self._atomic_write(payload)
        logger.info(
            "auth_profiles.upsert agent_id=%s profile_id=%s type=%s",
            self.agent_id, profile_id, credential.type,
        )

    def delete(self, profile_id: str) -> bool:
        """Remove a single profile. Returns ``True`` if it existed."""
        with self.with_lock():
            payload = self._read_payload()
            if profile_id not in payload[_PROFILES_KEY]:
                return False
            del payload[_PROFILES_KEY][profile_id]
            payload[_USAGE_KEY].pop(profile_id, None)
            self._atomic_write(payload)
        logger.info(
            "auth_profiles.delete agent_id=%s profile_id=%s",
            self.agent_id, profile_id,
        )
        return True

    def update_with_lock(
        self,
        updater: Callable[[dict[str, AuthProfileCredential]], bool],
    ) -> dict[str, AuthProfileCredential]:
        """Read-modify-write the whole profiles dict under the lock.

        ``updater`` receives a mutable mapping and returns ``True`` to
        commit, ``False`` to abandon the change. The mapping holds the
        decoded :class:`AuthProfileCredential` objects; on commit we
        re-serialise to JSON. This is the equivalent of openclaw's
        ``updateAuthProfileStoreWithLock`` and is the supported way to
        mirror an OAuth refresh across multiple profile ids in one
        atomic write.
        """
        with self.with_lock():
            payload = self._read_payload()
            decoded = {
                str(pid): credential_from_dict(raw)
                for pid, raw in payload[_PROFILES_KEY].items()
            }
            should_commit = updater(decoded)
            if not should_commit:
                return decoded
            payload[_PROFILES_KEY] = {
                pid: cred.to_dict() for pid, cred in decoded.items()
            }
            self._atomic_write(payload)
            return decoded

    def update_usage(
        self,
        profile_id: str,
        updater: Callable[[ProfileUsageStats], ProfileUsageStats],
    ) -> ProfileUsageStats:
        """Atomically replace a profile's usage stats."""
        if not profile_id or not isinstance(profile_id, str):
            raise ValueError("profile_id must be a non-empty string")
        with self.with_lock():
            payload = self._read_payload()
            current = ProfileUsageStats.from_dict(
                payload[_USAGE_KEY].get(profile_id, {})
            )
            updated = updater(current)
            payload[_USAGE_KEY][profile_id] = updated.to_dict()
            self._atomic_write(payload)
            return updated
