"""Tests for the FERAL perception fusion engine."""
import pytest
from perception.fusion import PerceptionFrame, PerceptionEngine


class TestPerceptionFrame:
    def test_defaults(self):
        frame = PerceptionFrame()
        assert frame.heart_rate == 0
        assert frame.activity_state == "unknown"
        assert frame.has_vision is False

    def test_system_context_empty(self):
        frame = PerceptionFrame()
        ctx = frame.to_system_context()
        assert ctx == "No sensor data available."

    def test_system_context_with_sensors(self):
        frame = PerceptionFrame(
            heart_rate=85,
            spo2_pct=98,
            activity_state="walking",
            ambient_light_lux=500,
            battery_pct=75,
        )
        ctx = frame.to_system_context()
        assert "HR=85bpm" in ctx
        assert "SpO2=98%" in ctx
        assert "State=walking" in ctx
        assert "Light=500lux" in ctx
        assert "Battery=75%" in ctx

    def test_system_context_high_hr_alert(self):
        frame = PerceptionFrame(heart_rate=155)
        ctx = frame.to_system_context()
        assert "critically high" in ctx.lower()

    def test_system_context_elevated_hr(self):
        frame = PerceptionFrame(heart_rate=110)
        ctx = frame.to_system_context()
        assert "elevated" in ctx.lower()

    def test_system_context_with_vision(self):
        frame = PerceptionFrame(
            has_vision=True,
            vision_data_url="data:image/jpeg;base64,abc",
            scene_description="Office with whiteboard",
            detected_objects=["whiteboard", "laptop"],
        )
        ctx = frame.to_system_context()
        assert "Camera feed" in ctx
        assert "Office" in ctx
        assert "whiteboard" in ctx

    def test_to_llm_user_content_text_only(self):
        frame = PerceptionFrame()
        content = frame.to_llm_user_content("hello")
        assert content == "hello"

    def test_to_llm_user_content_with_vision(self):
        frame = PerceptionFrame(
            has_vision=True,
            vision_data_url="data:image/jpeg;base64,abc123",
        )
        content = frame.to_llm_user_content("what do you see?")
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"

    def test_head_pose_context(self):
        frame = PerceptionFrame(head_pose=[25.0, -10.0, 5.0])
        ctx = frame.to_system_context()
        assert "Head pose" in ctx

    def test_gesture_context(self):
        frame = PerceptionFrame(gesture="nod")
        ctx = frame.to_system_context()
        assert "Gesture" in ctx
        assert "nod" in ctx


class TestPerceptionEngine:
    def test_get_frame_creates_new(self):
        engine = PerceptionEngine()
        frame = engine.get_frame("s1")
        assert isinstance(frame, PerceptionFrame)

    def test_get_frame_returns_same(self):
        engine = PerceptionEngine()
        f1 = engine.get_frame("s1")
        f1.heart_rate = 80
        f2 = engine.get_frame("s1")
        assert f2.heart_rate == 80

    def test_update_sensors_structured(self):
        engine = PerceptionEngine()
        engine.update_sensors("s1", {
            "vitals": {"ppg_heart_rate": 72, "spo2_pct": 97},
            "imu": {"head_pose_euler": [5.0, -3.0, 0.0]},
            "environment": {"ambient_light_lux": 300},
            "device": {"battery_pct": 88},
            "inferred_state": "resting",
        })
        frame = engine.get_frame("s1")
        assert frame.heart_rate == 72
        assert frame.spo2_pct == 97
        assert frame.ambient_light_lux == 300
        assert frame.battery_pct == 88
        assert frame.activity_state == "resting"

    def test_update_sensors_flat(self):
        engine = PerceptionEngine()
        engine.update_sensors("s1", {"heart_rate_bpm": 65, "battery_pct": 50})
        frame = engine.get_frame("s1")
        assert frame.heart_rate == 65
        assert frame.battery_pct == 50

    def test_update_audio(self):
        engine = PerceptionEngine()
        engine.update_audio_context("s1", ambient="traffic", transcript="turn left")
        frame = engine.get_frame("s1")
        assert frame.audio_ambient == "traffic"
        assert frame.transcript == "turn left"

    def test_update_gesture(self):
        engine = PerceptionEngine()
        engine.update_gesture("s1", "swipe_left")
        assert engine.get_frame("s1").gesture == "swipe_left"

    def test_update_connected_nodes(self):
        engine = PerceptionEngine()
        engine.update_connected_nodes("s1", ["glasses-w300", "robot-arm"])
        assert engine.get_frame("s1").connected_nodes == ["glasses-w300", "robot-arm"]

    def test_clear(self):
        engine = PerceptionEngine()
        engine.get_frame("s1").heart_rate = 80
        engine.clear("s1")
        assert engine.get_frame("s1").heart_rate == 0

    def test_session_isolation(self):
        engine = PerceptionEngine()
        engine.update_sensors("s1", {"vitals": {"ppg_heart_rate": 72}})
        engine.update_sensors("s2", {"vitals": {"ppg_heart_rate": 90}})
        assert engine.get_frame("s1").heart_rate == 72
        assert engine.get_frame("s2").heart_rate == 90
