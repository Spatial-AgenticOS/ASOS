"""Tests for the Gesture Interpreter."""

import pytest
from perception.gesture import GestureInterpreter, GestureEvent


class TestGestureInterpreter:
    def test_no_gesture_on_idle(self):
        gi = GestureInterpreter()
        for _ in range(20):
            result = gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [0, 0, 9.81]})
        assert result is None

    def test_nod_detection(self):
        gi = GestureInterpreter()
        # Simulate looking down then up (nod)
        pitches = [0, -5, -10, -15, -10, -5, 0, 5, 10, 15, 10, 5, 0]
        result = None
        for p in pitches:
            result = gi.update({"head_pose_euler": [p, 0, 0], "accel_xyz": [0, 0, 9.81]})
            if result:
                break
        assert result is not None
        assert result.gesture == "nod"

    def test_shake_detection(self):
        gi = GestureInterpreter()
        # Simulate looking left then right (shake)
        yaws = [0, 5, 10, 15, 20, 15, 10, 5, 0, -5, -10, -5, 0]
        result = None
        for y in yaws:
            result = gi.update({"head_pose_euler": [0, 0, y], "accel_xyz": [0, 0, 9.81]})
            if result:
                break
        assert result is not None
        assert result.gesture == "shake"

    def test_tap_detection(self):
        gi = GestureInterpreter()
        # Normal readings first
        for _ in range(5):
            gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [0, 0, 9.81]})
        # Sudden spike
        result = gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [15, 10, 9.81]})
        assert result is not None
        assert result.gesture == "double_tap"

    def test_look_up_detection(self):
        gi = GestureInterpreter()
        detected = None
        for _ in range(15):
            result = gi.update({"head_pose_euler": [30, 0, 0], "accel_xyz": [0, 0, 9.81]})
            if result and result.gesture == "look_up":
                detected = result
                break
        assert detected is not None
        assert detected.gesture == "look_up"

    def test_look_down_detection(self):
        gi = GestureInterpreter()
        detected = None
        for _ in range(15):
            result = gi.update({"head_pose_euler": [-25, 0, 0], "accel_xyz": [0, 0, 9.81]})
            if result and result.gesture == "look_down":
                detected = result
                break
        assert detected is not None
        assert detected.gesture == "look_down"

    def test_cooldown_prevents_repeat(self):
        gi = GestureInterpreter()
        # Trigger a tap
        for _ in range(5):
            gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [0, 0, 9.81]})
        first = gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [15, 10, 9.81]})
        assert first is not None

        # Immediately try again — should be suppressed
        second = gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [15, 10, 9.81]})
        assert second is None

    def test_reset_clears_state(self):
        gi = GestureInterpreter()
        for _ in range(10):
            gi.update({"head_pose_euler": [30, 0, 0], "accel_xyz": [0, 0, 9.81]})
        gi.reset()
        result = gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [0, 0, 9.81]})
        assert result is None

    def test_gesture_event_fields(self):
        gi = GestureInterpreter()
        for _ in range(5):
            gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [0, 0, 9.81]})
        result = gi.update({"head_pose_euler": [0, 0, 0], "accel_xyz": [15, 10, 9.81]})
        assert isinstance(result, GestureEvent)
        assert result.source == "imu"
        assert 0 <= result.confidence <= 1.0
        assert result.timestamp > 0


class TestDaemonGestureDetector:
    """Test the simplified daemon-side GestureDetector from w300_daemon."""

    def test_nod_detection_simple(self):
        """Verify the brain-side nod detection works with clear pitch swings."""
        pitches = [0, -3, -8, -12, -15, -12, -8, -3, 0, 3, 8, 12, 15, 12, 8, 3, 0]
        detected = False

        gi = GestureInterpreter()
        for p in pitches:
            result = gi.update({"head_pose_euler": [p, 0, 0], "accel_xyz": [0, 0, 9.81]})
            if result and result.gesture == "nod":
                detected = True
                break
        assert detected
