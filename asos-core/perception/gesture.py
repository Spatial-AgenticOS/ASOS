"""
THEORA Gesture Interpreter
============================
Interprets IMU data (accelerometer, gyroscope) from smart glasses
into discrete gesture events: nod, shake, look_up, look_down, tilt.

The interpreter maintains a sliding window of head pose / acceleration
and detects patterns using simple threshold-based state machines.
"""

from __future__ import annotations
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("theora.gesture")


@dataclass
class GestureEvent:
    gesture: str  # "nod", "shake", "look_up", "look_down", "double_tap", "tilt_left", "tilt_right"
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)
    source: str = "imu"


class GestureInterpreter:
    """
    Stateful interpreter that converts raw IMU streams into gesture events.
    Designed for head-mounted devices (smart glasses).
    """

    COOLDOWN_S = 1.5  # min gap between same gesture type

    # Thresholds (tuned for typical head-mounted IMU @ ~20 Hz)
    NOD_PITCH_DELTA = 15.0       # degrees
    SHAKE_YAW_DELTA = 20.0       # degrees
    LOOK_UP_PITCH = 25.0         # degrees above neutral
    LOOK_DOWN_PITCH = -20.0      # degrees below neutral
    TILT_ROLL = 25.0             # degrees
    TAP_ACCEL_SPIKE = 18.0       # m/s² above gravity

    def __init__(self, window_size: int = 30):
        self._pitch_history: deque[float] = deque(maxlen=window_size)
        self._yaw_history: deque[float] = deque(maxlen=window_size)
        self._roll_history: deque[float] = deque(maxlen=window_size)
        self._accel_history: deque[float] = deque(maxlen=window_size)
        self._last_gesture_time: dict[str, float] = {}

    def update(self, imu_data: dict) -> Optional[GestureEvent]:
        """
        Feed a new IMU sample and return a gesture event if detected.

        Expected imu_data keys:
          - head_pose_euler: [pitch, roll, yaw] in degrees
          - accel_xyz: [x, y, z] in m/s²
        """
        euler = imu_data.get("head_pose_euler", [])
        accel = imu_data.get("accel_xyz", [0, 0, 0])

        if len(euler) >= 3:
            pitch, roll, yaw = euler[0], euler[1], euler[2]
            self._pitch_history.append(pitch)
            self._yaw_history.append(yaw)
            self._roll_history.append(roll)

        accel_mag = math.sqrt(sum(a * a for a in accel))
        self._accel_history.append(accel_mag)

        return self._detect()

    def _detect(self) -> Optional[GestureEvent]:
        """Run all gesture detectors in priority order."""
        now = time.time()

        # Double tap (sudden acceleration spike) — highest priority
        if self._check_cooldown("double_tap", now) and self._detect_tap():
            return self._emit("double_tap", 0.85, now)

        # Sustained look up/down — check before nod to avoid false nod from sustained pose
        if self._check_cooldown("look_up", now) and self._detect_look_up():
            return self._emit("look_up", 0.8, now)

        if self._check_cooldown("look_down", now) and self._detect_look_down():
            return self._emit("look_down", 0.8, now)

        # Nod (pitch oscillation: down then up)
        if self._check_cooldown("nod", now) and self._detect_nod():
            return self._emit("nod", 0.9, now)

        # Head shake (yaw oscillation: left-right-left)
        if self._check_cooldown("shake", now) and self._detect_shake():
            return self._emit("shake", 0.9, now)

        # Head tilt
        if self._check_cooldown("tilt_left", now) and self._detect_tilt("left"):
            return self._emit("tilt_left", 0.75, now)

        if self._check_cooldown("tilt_right", now) and self._detect_tilt("right"):
            return self._emit("tilt_right", 0.75, now)

        return None

    def _check_cooldown(self, gesture: str, now: float) -> bool:
        last = self._last_gesture_time.get(gesture, 0)
        return (now - last) >= self.COOLDOWN_S

    def _emit(self, gesture: str, confidence: float, now: float) -> GestureEvent:
        self._last_gesture_time[gesture] = now
        logger.info(f"Gesture detected: {gesture} (confidence={confidence})")
        return GestureEvent(gesture=gesture, confidence=confidence, timestamp=now)

    def _detect_nod(self) -> bool:
        if len(self._pitch_history) < 10:
            return False
        recent = list(self._pitch_history)[-10:]
        max_p = max(recent)
        min_p = min(recent)
        delta = max_p - min_p
        if delta < self.NOD_PITCH_DELTA:
            return False
        # Check for down-up pattern (min before max in the window)
        min_idx = recent.index(min_p)
        max_idx = len(recent) - 1 - recent[::-1].index(max_p)
        return min_idx < max_idx

    def _detect_shake(self) -> bool:
        if len(self._yaw_history) < 12:
            return False
        recent = list(self._yaw_history)[-12:]
        max_y = max(recent)
        min_y = min(recent)
        return (max_y - min_y) >= self.SHAKE_YAW_DELTA

    def _detect_look_up(self) -> bool:
        if len(self._pitch_history) < 5:
            return False
        recent = list(self._pitch_history)[-5:]
        avg = sum(recent) / len(recent)
        return avg >= self.LOOK_UP_PITCH

    def _detect_look_down(self) -> bool:
        if len(self._pitch_history) < 5:
            return False
        recent = list(self._pitch_history)[-5:]
        avg = sum(recent) / len(recent)
        return avg <= self.LOOK_DOWN_PITCH

    def _detect_tilt(self, direction: str) -> bool:
        if len(self._roll_history) < 5:
            return False
        recent = list(self._roll_history)[-5:]
        avg = sum(recent) / len(recent)
        if direction == "left":
            return avg >= self.TILT_ROLL
        return avg <= -self.TILT_ROLL

    def _detect_tap(self) -> bool:
        if len(self._accel_history) < 3:
            return False
        recent = list(self._accel_history)[-3:]
        return max(recent) >= self.TAP_ACCEL_SPIKE

    def reset(self):
        self._pitch_history.clear()
        self._yaw_history.clear()
        self._roll_history.clear()
        self._accel_history.clear()
        self._last_gesture_time.clear()
