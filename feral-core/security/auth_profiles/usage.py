"""
W16 — placeholder per-profile usage tracker.

**This module intentionally does NOT implement the cooldown / failover
state machine.** ``W19`` (per-roadmap §10) owns the canonical two-lane
FSM (cooldown vs disabled, exponential backoff, ``Retry-After`` honor,
per-model scope, per-key rotation). When W19 lands it will swap the
:class:`ProfileUsageTracker` body below for the real FSM without
changing the on-disk shape — :class:`security.auth_profiles.types.ProfileUsageStats`
is forward-compatible by design.

Until then this tracker:

* persists ``success_count`` / ``failure_count`` / ``last_used_at`` to
  ``auth_profiles.json`` so the file format never has to be migrated
  when W19 ships;
* exposes ``record_success`` / ``record_failure`` / ``stats`` so callers
  can already start emitting telemetry;
* deliberately does NOT compute any cooldown timer — calling
  :meth:`should_skip` always returns ``False`` because no W16 caller
  has authority to disable a profile.

W19 will replace ``record_failure`` with the failure-classification +
cooldown logic from openclaw's ``auth-profiles/usage.ts`` while
preserving this signature.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .types import ProfileUsageStats

if TYPE_CHECKING:
    from .store import AuthProfileFileStore


logger = logging.getLogger("feral.auth_profiles.usage")


def _now_ms() -> int:
    return int(time.time() * 1000)


class ProfileUsageTracker:
    """Persisted per-profile success/failure counters.

    W19 supersedes the inner FSM — this class will keep the same public
    surface but its body will be replaced with the two-lane cooldown
    state machine. The on-disk
    :class:`security.auth_profiles.types.ProfileUsageStats` shape is the
    contract; do not add fields here without also extending that
    dataclass.
    """

    def __init__(self, store: "AuthProfileFileStore") -> None:
        self._store = store

    def stats(self, profile_id: str) -> ProfileUsageStats:
        return self._store.usage(profile_id)

    def record_success(self, profile_id: str) -> ProfileUsageStats:
        """Bump the success counter and stamp ``last_used_at``."""
        return self._store.update_usage(
            profile_id,
            lambda s: ProfileUsageStats(
                success_count=s.success_count + 1,
                failure_count=s.failure_count,
                last_used_at=_now_ms(),
            ),
        )

    def record_failure(self, profile_id: str, *, reason: str = "unknown") -> ProfileUsageStats:
        """Bump the failure counter and stamp ``last_used_at``.

        ``reason`` is accepted today but not persisted — W19 will widen
        :class:`ProfileUsageStats` with a per-reason histogram and a
        cooldown-until timestamp. Logging it now means W19's failure
        analysis can grep historical logs for failure patterns.
        """
        logger.info(
            "auth_profiles.usage.failure profile_id=%s reason=%s",
            profile_id, reason,
        )
        return self._store.update_usage(
            profile_id,
            lambda s: ProfileUsageStats(
                success_count=s.success_count,
                failure_count=s.failure_count + 1,
                last_used_at=_now_ms(),
            ),
        )

    def should_skip(self, profile_id: str) -> bool:
        """Always ``False`` in W16. W19 will return ``True`` while the
        profile is in cooldown or disabled.

        The method exists so call sites can already wire the
        skip-on-cooldown branch and W19 only has to ship the FSM —
        not chase down call sites."""
        del profile_id
        return False
