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

    def update_sensors(self, session_id: str, sensors: dict):
        """Update the perception frame with structured telemetry data."""
        frame = self.get_frame(session_id)
        frame.timestamp = time.time()

        vitals = sensors.get("vitals", {})
        imu = sensors.get("imu", {})
        env = sensors.get("environment", {})
        device = sensors.get("device", {})
        inferred = sensors.get("inferred_state", "")

        # Vitals — support both structured and flat
        frame.heart_rate = vitals.get("ppg_heart_rate") or sensors.get("ppg_heart_rate") or sensors.get("heart_rate_bpm") or frame.heart_rate
        frame.spo2_pct = vitals.get("spo2_pct") or sensors.get("spo2_pct") or frame.spo2_pct
        frame.skin_temperature_c = vitals.get("skin_temperature_c") or frame.skin_temperature_c

        # IMU
        frame.head_pose = imu.get("head_pose_euler") or frame.head_pose

        # Environment
        frame.ambient_light_lux = env.get("ambient_light_lux") or frame.ambient_light_lux

        # Device
        frame.battery_pct = device.get("battery_pct") or sensors.get("battery_pct") or frame.battery_pct

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
