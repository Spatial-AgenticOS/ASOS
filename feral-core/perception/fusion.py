"""
FERAL Perception Fusion Engine
=================================
The core differentiator: fuses camera, audio, and sensor data into a
single unified PerceptionFrame that becomes the LLM's ground truth.

From Vision.md:
  "The brain's input is NOT text. It's a fused multimodal stream."

  {
    "timestamp": 1743000000,
    "audio": <transcript>,
    "vision": { scene_description, detected_objects, text_in_scene },
    "sensors": { heart_rate, activity, location, ambient_light },
    "gesture": null
  }
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api.server import VisionBuffer

logger = logging.getLogger("feral.perception")


@dataclass
class PerceptionFrame:
    """
    A single fused perception snapshot.
    Every LLM invocation receives the latest frame as context.
    """
    timestamp: float = field(default_factory=time.time)

    # Audio
    transcript: str = ""
    audio_ambient: str = ""  # "silence", "speech", "music", "traffic", etc.

    # Vision
    has_vision: bool = False
    scene_description: str = ""
    detected_objects: list[str] = field(default_factory=list)
    text_in_scene: list[str] = field(default_factory=list)
    vision_data_url: str = ""  # base64 data URL of the latest frame

    # Sensors
    heart_rate: int = 0
    spo2_pct: int = 0
    skin_temperature_c: float = 0.0
    activity_state: str = "unknown"  # resting, walking, running, stressed

    # Per-metric sample times (operator report 2026-05-09: fake-looking
    # HR=115 alert when glasses weren't connected — actual cause was
    # Apple HealthKit returning a hours-stale resting-HR sample as
    # "current". Proactive alerts now read these timestamps to gate on
    # freshness AND surface the source so the user knows where it came
    # from). Default 0.0 means "never seen". Updated by
    # ``update_sensors`` whenever the matching metric receives a fresh
    # value with a known timestamp.
    heart_rate_sample_ts: float = 0.0
    heart_rate_source: str = ""  # e.g. "apple_healthkit", "theora_w300"
    spo2_sample_ts: float = 0.0
    spo2_source: str = ""
    head_pose: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    ambient_light_lux: int = 0
    battery_pct: int = 100
    location: Optional[dict] = None  # {"lat": float, "lon": float}

    # Gesture
    gesture: Optional[str] = None  # "tap", "swipe_left", "nod", etc.

    # Device
    connected_nodes: list[str] = field(default_factory=list)

    def to_system_context(self) -> str:
        """
        Serialize into a compact LLM-injectable context block.
        Only includes non-empty fields to minimize token usage.
        """
        sections = []

        # Sensor block
        sensor_parts = []
        if self.heart_rate:
            sensor_parts.append(f"HR={self.heart_rate}bpm")
        if self.spo2_pct:
            sensor_parts.append(f"SpO2={self.spo2_pct}%")
        if self.skin_temperature_c:
            sensor_parts.append(f"Temp={self.skin_temperature_c}°C")
        if self.activity_state and self.activity_state != "unknown":
            sensor_parts.append(f"State={self.activity_state}")
        if self.ambient_light_lux:
            sensor_parts.append(f"Light={self.ambient_light_lux}lux")
        if self.battery_pct < 100:
            sensor_parts.append(f"Battery={self.battery_pct}%")
        if sensor_parts:
            sections.append("Sensors: " + " | ".join(sensor_parts))

        # Adaptive behavior hints
        if self.heart_rate > 140:
            sections.append("USER ALERT: Heart rate critically high. Be extremely concise.")
        elif self.heart_rate > 100:
            sections.append("User's heart rate is elevated. Keep responses brief.")

        # Head pose
        if any(abs(v) > 15 for v in self.head_pose):
            sections.append(f"Head pose (pitch/roll/yaw): {[round(v, 1) for v in self.head_pose]}")

        # Location
        if self.location:
            sections.append(f"Location: lat={self.location.get('lat')}, lon={self.location.get('lon')}")

        # Audio context
        if self.audio_ambient and self.audio_ambient != "silence":
            sections.append(f"Audio environment: {self.audio_ambient}")

        # Vision context
        if self.has_vision:
            sections.append("Camera feed is active — a frame is attached to this message.")
            if self.scene_description:
                sections.append(f"Scene: {self.scene_description}")
            if self.detected_objects:
                sections.append(f"Objects: {', '.join(self.detected_objects[:10])}")
            if self.text_in_scene:
                sections.append(f"Text visible: {', '.join(self.text_in_scene[:5])}")

        # Gesture
        if self.gesture:
            sections.append(f"Gesture detected: {self.gesture}")

        # Nodes
        if self.connected_nodes:
            sections.append(f"Connected nodes: {', '.join(self.connected_nodes)}")

        return "\n".join(sections) if sections else "No sensor data available."

    def to_llm_user_content(self, text: str) -> dict | list:
        """
        Build the user message content, optionally attaching a vision frame
        as an OpenAI-compatible image_url content block.
        """
        if self.has_vision and self.vision_data_url:
            return [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": self.vision_data_url, "detail": "low"}},
            ]
        return text


class PerceptionEngine:
    """
    Maintains the latest PerceptionFrame for each session by fusing
    data from all input streams (telemetry, vision, audio).
    """

    def __init__(self):
        self._frames: dict[str, PerceptionFrame] = {}

    def get_frame(self, session_id: str) -> PerceptionFrame:
        if session_id not in self._frames:
            self._frames[session_id] = PerceptionFrame()
        return self._frames[session_id]

    @staticmethod
    def _first_valid(*values):
        """Return the first value that is not None, preserving valid zeros."""
        for v in values:
            if v is not None:
                return v
        return None

    def update_sensors(self, session_id: str, sensors: dict):
        """Update the perception frame with structured telemetry data."""
        frame = self.get_frame(session_id)
        frame.timestamp = time.time()

        vitals = sensors.get("vitals", {})
        imu = sensors.get("imu", {})
        env = sensors.get("environment", {})
        device = sensors.get("device", {})
        inferred = sensors.get("inferred_state", "")

        _fv = self._first_valid

        # Vitals — support both structured and flat
        _hr = _fv(vitals.get("ppg_heart_rate"), sensors.get("ppg_heart_rate"), sensors.get("heart_rate_bpm"))
        if _hr is not None:
            frame.heart_rate = _hr
            # Stamp the receive time as the sample-fresh time. If the
            # caller passes an explicit ``sample_ts`` (e.g. iOS
            # HealthKitAdapter forwards ``HKQuantitySample.endDate``)
            # we honor that — see ``test_proactive_freshness_gate.py``
            # for the contract.
            _hr_ts = _fv(
                vitals.get("ppg_heart_rate_sample_ts"),
                sensors.get("ppg_heart_rate_sample_ts"),
                sensors.get("heart_rate_sample_ts"),
            )
            frame.heart_rate_sample_ts = float(_hr_ts) if _hr_ts is not None else time.time()
            _hr_src = _fv(
                vitals.get("ppg_heart_rate_source"),
                sensors.get("source"),
                sensors.get("heart_rate_source"),
            )
            if _hr_src is not None:
                frame.heart_rate_source = str(_hr_src)
        _spo2 = _fv(vitals.get("spo2_pct"), sensors.get("spo2_pct"))
        if _spo2 is not None:
            frame.spo2_pct = _spo2
            _spo2_ts = _fv(
                vitals.get("spo2_sample_ts"),
                sensors.get("spo2_sample_ts"),
            )
            frame.spo2_sample_ts = float(_spo2_ts) if _spo2_ts is not None else time.time()
            _spo2_src = _fv(
                vitals.get("spo2_source"),
                sensors.get("source"),
                sensors.get("spo2_source"),
            )
            if _spo2_src is not None:
                frame.spo2_source = str(_spo2_src)
        _temp = vitals.get("skin_temperature_c")
        if _temp is not None:
            frame.skin_temperature_c = _temp

        # IMU
        _pose = imu.get("head_pose_euler")
        if _pose is not None:
            frame.head_pose = _pose

        # Environment
        _lux = env.get("ambient_light_lux")
        if _lux is not None:
            frame.ambient_light_lux = _lux

        # Device
        _batt = _fv(device.get("battery_pct"), sensors.get("battery_pct"))
        if _batt is not None:
            frame.battery_pct = _batt

        # Inferred state
        if inferred:
            frame.activity_state = inferred

        # Location (from biometric or GPS source)
        gps = sensors.get("gps")
        if gps:
            frame.location = gps

    def update_vision(self, session_id: str, vision_buffer: "VisionBuffer", node_id: str):
        """Update vision data from the latest frame in the buffer."""
        frame = self.get_frame(session_id)
        data_url = vision_buffer.latest_data_url(node_id)
        if data_url:
            frame.has_vision = True
            frame.vision_data_url = data_url
            frame.timestamp = time.time()

            latest = vision_buffer.latest(node_id)
            if latest:
                meta = latest.get("metadata", {})
                frame.scene_description = meta.get("scene_description", "")
                frame.detected_objects = meta.get("detected_objects", [])
                frame.text_in_scene = meta.get("text_in_scene", [])

    def update_audio_context(self, session_id: str, ambient: str = "", transcript: str = ""):
        frame = self.get_frame(session_id)
        if ambient:
            frame.audio_ambient = ambient
        if transcript:
            frame.transcript = transcript

    def update_gesture(self, session_id: str, gesture: str):
        frame = self.get_frame(session_id)
        frame.gesture = gesture
        frame.timestamp = time.time()

    def update_connected_nodes(self, session_id: str, nodes: list[str]):
        frame = self.get_frame(session_id)
        frame.connected_nodes = nodes

    def clear(self, session_id: str):
        self._frames.pop(session_id, None)
