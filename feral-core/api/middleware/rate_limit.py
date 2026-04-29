"""Per-IP sliding-window rate limiter for high-risk pair endpoints.

The brain runs as a single process per machine, so a process-local
in-memory counter is sufficient — there is no horizontal scaling story
that would need Redis. If the operator restarts the brain, the counters
reset; that is the intended trade-off (counters are anti-abuse, not
anti-DoS).

The current consumer is ``POST /api/devices/pair/code/claim`` (see
``feral-core/api/routes/devices.py``). The 8-character base32 codes have
~38 bits of entropy; combined with TTL=600s and 5 wrong attempts per
IP per 15 minutes, brute force is infeasible without bot-net coordination
that would already trip every other auth surface on the brain.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class SlidingWindowLimiter:
    """5 attempts / 15 minutes by default. Configurable for tests.

    Each call to ``allow(key)`` consults the deque for ``key``, evicts
    expired timestamps, and returns ``True`` if the deque is under the
    limit. Failures are recorded with ``record_failure(key)`` so callers
    can choose not to charge a successful attempt against the budget.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: float = 15 * 60):
        self.max_attempts = int(max_attempts)
        self.window_seconds = float(window_seconds)
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.monotonic()

    def _evict_expired(self, key: str, now: float) -> None:
        dq = self._failures[key]
        cutoff = now - self.window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()

    def allow(self, key: str) -> bool:
        """Check whether the next attempt from ``key`` is permitted."""
        if not key:
            return True
        with self._lock:
            now = self._now()
            self._evict_expired(key, now)
            return len(self._failures[key]) < self.max_attempts

    def record_failure(self, key: str) -> None:
        """Charge one failure against the budget."""
        if not key:
            return
        with self._lock:
            now = self._now()
            self._evict_expired(key, now)
            self._failures[key].append(now)

    def retry_after(self, key: str) -> int:
        """Seconds until ``key`` may try again. 0 if currently allowed."""
        if not key:
            return 0
        with self._lock:
            now = self._now()
            self._evict_expired(key, now)
            dq = self._failures[key]
            if len(dq) < self.max_attempts:
                return 0
            oldest = dq[0]
            elapsed = now - oldest
            remaining = self.window_seconds - elapsed
            return max(1, int(remaining))

    def reset(self, key: str | None = None) -> None:
        """Test helper: clear failures for one key, or all keys."""
        with self._lock:
            if key is None:
                self._failures.clear()
            else:
                self._failures.pop(key, None)


code_claim_limiter = SlidingWindowLimiter(max_attempts=5, window_seconds=15 * 60)
