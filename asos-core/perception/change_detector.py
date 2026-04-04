"""
THEORA Change Detector — Intelligent Vision Triggering
========================================================
Lightweight frame-difference detector that decides WHEN to invoke
the expensive VLM.  Uses histogram comparison instead of ML so it
runs on any hardware with near-zero latency.

Trigger reasons:
  scene_change  — pixel histogram diverged beyond threshold
  periodic      — maximum interval elapsed without any analysis
  user_request  — user explicitly asked ("what do you see?")
  motion_start  — first frame after a period of stillness
"""

from __future__ import annotations
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("theora.perception.change")


@dataclass
class ChangeEvent:
    """Emitted when the detector decides the VLM should run."""
    trigger_reason: str  # scene_change | periodic | user_request | motion_start
    change_score: float  # 0.0 (identical) → 1.0 (completely different)
    node_id: str = ""
    elapsed_since_last: float = 0.0


@dataclass
class _NodeState:
    """Per-node tracking state for the change detector."""
    last_histogram: list[int] = field(default_factory=list)
    last_analysis_time: float = 0.0
    last_frame_time: float = 0.0
    consecutive_still_frames: int = 0
    was_still: bool = False


class ChangeDetector:
    """
    Stateful per-node frame comparator.
    
    Call `should_analyze(node_id, frame_b64)` on every incoming frame.
    Returns a `ChangeEvent` if the VLM should run, else `None`.
    """

    def __init__(
        self,
        *,
        change_threshold: float = 0.30,
        min_interval: float = 2.0,
        max_interval: float = 30.0,
        still_frame_count: int = 5,
        histogram_bins: int = 64,
    ):
        self._threshold = change_threshold
        self._min_interval = min_interval
        self._max_interval = max_interval
        self._still_count = still_frame_count
        self._bins = histogram_bins
        self._nodes: dict[str, _NodeState] = {}

    def _get_state(self, node_id: str) -> _NodeState:
        if node_id not in self._nodes:
            self._nodes[node_id] = _NodeState()
        return self._nodes[node_id]

    def force_trigger(self, node_id: str, reason: str = "user_request") -> ChangeEvent:
        """Bypass all throttling — user explicitly asked."""
        ns = self._get_state(node_id)
        ns.last_analysis_time = time.time()
        return ChangeEvent(
            trigger_reason=reason,
            change_score=1.0,
            node_id=node_id,
            elapsed_since_last=time.time() - ns.last_analysis_time,
        )

    def should_analyze(
        self, node_id: str, frame_b64: str, encoding: str = "jpeg",
    ) -> Optional[ChangeEvent]:
        """
        Compare the incoming frame against the last frame for this node.
        Returns a ChangeEvent if the VLM should be triggered.
        """
        now = time.time()
        ns = self._get_state(node_id)
        ns.last_frame_time = now
        elapsed = now - ns.last_analysis_time

        if elapsed < self._min_interval:
            return None

        histogram = self._compute_histogram(frame_b64)
        if not histogram:
            return None

        if not ns.last_histogram:
            ns.last_histogram = histogram
            ns.last_analysis_time = now
            return ChangeEvent(
                trigger_reason="scene_change",
                change_score=1.0,
                node_id=node_id,
                elapsed_since_last=elapsed,
            )

        score = self._histogram_distance(ns.last_histogram, histogram)

        if score >= self._threshold:
            ns.last_histogram = histogram
            ns.last_analysis_time = now
            ns.consecutive_still_frames = 0

            reason = "scene_change"
            if ns.was_still:
                reason = "motion_start"
                ns.was_still = False

            return ChangeEvent(
                trigger_reason=reason,
                change_score=score,
                node_id=node_id,
                elapsed_since_last=elapsed,
            )

        ns.consecutive_still_frames += 1
        if ns.consecutive_still_frames >= self._still_count:
            ns.was_still = True

        if elapsed >= self._max_interval:
            ns.last_histogram = histogram
            ns.last_analysis_time = now
            return ChangeEvent(
                trigger_reason="periodic",
                change_score=score,
                node_id=node_id,
                elapsed_since_last=elapsed,
            )

        return None

    def _compute_histogram(self, frame_b64: str) -> list[int]:
        """Compute a grayscale luminance histogram from a base64-encoded image."""
        try:
            raw = base64.b64decode(frame_b64)
            if len(raw) < 100:
                return []

            luminance_values = self._extract_luminance_samples(raw)
            if not luminance_values:
                return []

            hist = [0] * self._bins
            bin_width = 256.0 / self._bins
            for val in luminance_values:
                idx = min(int(val / bin_width), self._bins - 1)
                hist[idx] += 1
            return hist

        except Exception:
            return []

    def _extract_luminance_samples(self, raw_bytes: bytes) -> list[int]:
        """
        Extract approximate luminance samples from raw image bytes.
        For JPEG/PNG we sample raw byte values at regular intervals
        as a proxy for pixel luminance.  Imperfect but fast and
        sufficient for change detection.
        """
        if len(raw_bytes) < 200:
            return []

        header_skip = min(200, len(raw_bytes) // 4)
        data = raw_bytes[header_skip:]

        step = max(1, len(data) // 2048)
        samples = [data[i] for i in range(0, len(data), step)]
        return samples[:2048]

    def _histogram_distance(self, h1: list[int], h2: list[int]) -> float:
        """
        Compute normalized histogram distance (0.0 = identical, 1.0 = maximally different).
        Uses chi-squared-like distance.
        """
        if len(h1) != len(h2):
            return 1.0

        total1 = sum(h1) or 1
        total2 = sum(h2) or 1

        distance = 0.0
        for a, b in zip(h1, h2):
            na = a / total1
            nb = b / total2
            denom = na + nb
            if denom > 0:
                distance += ((na - nb) ** 2) / denom

        return min(distance / 2.0, 1.0)

    def clear_node(self, node_id: str):
        self._nodes.pop(node_id, None)

    def stats(self) -> dict:
        return {
            "tracked_nodes": len(self._nodes),
            "threshold": self._threshold,
            "min_interval": self._min_interval,
            "max_interval": self._max_interval,
        }
