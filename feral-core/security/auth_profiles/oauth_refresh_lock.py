"""
W16 — cross-process file lock for OAuth credential refreshes.

Mirrors openclaw's ``auth-profiles/path-resolve.ts::resolveOAuthRefreshLockPath``
+ ``oauth-manager.ts``'s ``withFileLock`` wrapper. The lock prevents
the ``refresh_token_reused`` storm that hits when N processes share a
single OAuth profile and all attempt to refresh the same single-use
refresh token simultaneously: the first refresh succeeds and rotates
the token; every subsequent refresh sees the rotated token, gets
``invalid_grant``, and the provider revokes the WHOLE chain (see
``OPENCLAW_LESSONS.md`` §1 + §10 W16).

Semantics:

* The lock path is ``$FERAL_HOME/locks/oauth-refresh/sha256-<hex>``
  where ``<hex>`` is ``sha256(provider \\0 profile_id)``. The NUL
  separator makes it impossible to collide ``("a", "b:c")`` with
  ``("a:b", "c")`` by string concatenation.
* On POSIX we use ``fcntl.flock(LOCK_EX)`` — an advisory lock that all
  Python ``OAuthRefreshLock`` users honor. The lock is released when
  the file descriptor is closed (process exit or ``__exit__``).
* The lock file persists across runs by design — ``flock`` operates
  on the open file descriptor, not the inode, so leftover files are
  harmless and stay around to give the lock a stable path.
* Windows is unsupported in W16's first cut (FERAL is POSIX-first
  today). ``RuntimeError`` is raised explicitly so a Windows user sees
  a clear message instead of a silent broken refresh path.

The lock is intentionally *not* re-entrant. A process must hold at
most one OAuth refresh per (provider, profile_id). Re-entrance would
mask buggy code that recursively triggers a refresh inside a refresh.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .paths import resolve_locks_dir


logger = logging.getLogger("feral.auth_profiles.oauth_refresh_lock")


_LOCK_SUBDIR = "oauth-refresh"
# Default acquisition timeout. openclaw uses 30s for its OAuth refresh
# lock (`OAUTH_REFRESH_LOCK_OPTIONS`); we mirror that ceiling so a
# stuck refresh in process A surfaces as an explicit timeout in
# process B instead of an unbounded hang.
DEFAULT_TIMEOUT_SECONDS = 30.0
_POLL_INTERVAL_SECONDS = 0.05


class OAuthRefreshLockTimeout(TimeoutError):
    """Raised when :func:`acquire_oauth_refresh_lock` cannot acquire
    the lock within the requested deadline."""


def resolve_oauth_refresh_lock_path(provider: str, profile_id: str) -> Path:
    """Path of the refresh lock for ``(provider, profile_id)``.

    The hash is computed over ``provider`` + NUL + ``profile_id`` (UTF-8
    encoded) so two profiles that legitimately share an id across
    providers do not serialize against each other, and string
    concatenation can never collide two distinct pairs.

    The lock directory is **not** created here — that's the responsibility
    of :func:`acquire_oauth_refresh_lock` so the path resolver stays
    pure for tests.
    """
    if not isinstance(provider, str) or not provider:
        raise ValueError("provider must be a non-empty string")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("profile_id must be a non-empty string")
    h = hashlib.sha256()
    h.update(provider.encode("utf-8"))
    h.update(b"\x00")
    h.update(profile_id.encode("utf-8"))
    safe_id = f"sha256-{h.hexdigest()}"
    return resolve_locks_dir() / _LOCK_SUBDIR / safe_id


@contextmanager
def acquire_oauth_refresh_lock(
    provider: str,
    profile_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[Path]:
    """Hold the cross-process OAuth refresh lock for ``(provider, profile_id)``.

    Usage::

        with acquire_oauth_refresh_lock("google-codex", "google-codex:work"):
            new_creds = refresh_oauth_token(...)
            store.upsert("google-codex:work", new_creds)

    The body runs while every other process attempting to acquire the
    same lock is blocked. A second waiter that exceeds ``timeout`` raises
    :class:`OAuthRefreshLockTimeout` — the caller should re-read the
    profile from disk (the holder probably just rotated it) instead of
    forcing a second HTTP refresh.
    """
    if os.name != "posix":
        raise RuntimeError(
            "OAuth refresh lock requires POSIX fcntl.flock; Windows is not "
            "supported by W16. Run FERAL on macOS or Linux, or wait for "
            "the W18 supervisor port."
        )

    import fcntl

    lock_path = resolve_oauth_refresh_lock_path(provider, profile_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Open in append mode so the file is created on first acquisition
    # and the descriptor is writable (some flock backends refuse
    # exclusive locks on read-only fds). We never write content; the
    # file is just a stable inode the kernel can lock against.
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + max(0.0, timeout)
    acquired = False
    try:
        while True:
            acquire_failed_with: Optional[BaseException] = None
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as exc:
                acquire_failed_with = exc
            if time.monotonic() >= deadline:
                raise OAuthRefreshLockTimeout(
                    f"timed out after {timeout:.2f}s waiting for OAuth refresh "
                    f"lock at {lock_path} (provider={provider!r}, "
                    f"profile_id={profile_id!r}). Another process is currently "
                    f"refreshing this profile; reload the profile from disk "
                    f"and reuse the rotated credentials instead of forcing a "
                    f"second refresh."
                ) from acquire_failed_with
            time.sleep(_POLL_INTERVAL_SECONDS)
        logger.debug(
            "auth_profiles.oauth_refresh_lock.acquired provider=%s profile_id=%s",
            provider, profile_id,
        )
        yield lock_path
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
            logger.debug(
                "auth_profiles.oauth_refresh_lock.released provider=%s profile_id=%s",
                provider, profile_id,
            )
        os.close(fd)
