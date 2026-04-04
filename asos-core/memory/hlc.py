"""
THEORA Hybrid Logical Clock — Distributed causal ordering
===========================================================
HLC provides ordering guarantees without a central clock server.
Each event gets a (wall_clock_ms, counter, node_id) tuple that
respects both physical time and causality.

Used by the SyncEngine for conflict-free replication.
"""

from __future__ import annotations
import time
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class HLCTimestamp:
    """Immutable HLC timestamp — comparable and serializable."""
    wall_ms: int
    counter: int
    node_id: str = ""

    def to_tuple(self) -> tuple[int, int, str]:
        return (self.wall_ms, self.counter, self.node_id)

    def to_string(self) -> str:
        return f"{self.wall_ms}:{self.counter}:{self.node_id}"

    @staticmethod
    def from_string(s: str) -> "HLCTimestamp":
        parts = s.split(":", 2)
        return HLCTimestamp(
            wall_ms=int(parts[0]),
            counter=int(parts[1]),
            node_id=parts[2] if len(parts) > 2 else "",
        )

    @staticmethod
    def zero() -> "HLCTimestamp":
        return HLCTimestamp(wall_ms=0, counter=0, node_id="")


class HybridLogicalClock:
    """
    Per-node HLC instance.

    Guarantees:
    - Monotonically increasing timestamps
    - Respects causality: send(ts) < receive(ts)
    - Tracks physical time when possible
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._wall_ms: int = 0
        self._counter: int = 0

    def now(self) -> HLCTimestamp:
        """Generate a new timestamp for a local event."""
        physical = int(time.time() * 1000)

        if physical > self._wall_ms:
            self._wall_ms = physical
            self._counter = 0
        else:
            self._counter += 1

        return HLCTimestamp(
            wall_ms=self._wall_ms,
            counter=self._counter,
            node_id=self.node_id,
        )

    def receive(self, remote: HLCTimestamp) -> HLCTimestamp:
        """
        Update the clock after receiving a message from another node.
        Ensures the new timestamp is greater than both local and remote.
        """
        physical = int(time.time() * 1000)

        if physical > self._wall_ms and physical > remote.wall_ms:
            self._wall_ms = physical
            self._counter = 0
        elif remote.wall_ms > self._wall_ms:
            self._wall_ms = remote.wall_ms
            self._counter = remote.counter + 1
        elif self._wall_ms > remote.wall_ms:
            self._counter += 1
        else:
            # wall_ms are equal
            self._counter = max(self._counter, remote.counter) + 1

        return HLCTimestamp(
            wall_ms=self._wall_ms,
            counter=self._counter,
            node_id=self.node_id,
        )

    @property
    def current(self) -> HLCTimestamp:
        return HLCTimestamp(
            wall_ms=self._wall_ms,
            counter=self._counter,
            node_id=self.node_id,
        )
