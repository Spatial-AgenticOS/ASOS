"""
FERAL Protocol — The Wire Format
==================================
Every component in FERAL speaks this protocol.
Brain, Phone, Daemon, Robot — all use the same message envelope.
This is the single source of truth for all message types.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal, Any
from uuid import uuid4
from time import time


# ─────────────────────────────────────────────
# The Universal Message Envelope
# ─────────────────────────────────────────────

class FeralMessage(BaseModel):
    """Every message in the system uses this envelope."""
    msg_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    timestamp_ms: int = Field(default_factory=lambda: int(time() * 1000))
    hop: Literal["client", "brain", "daemon", "skill"] = "client"
    type: str  # Discriminator — see payload types below
    payload: dict = Field(default_factory=dict)


# ─────────────────────────────────────────────
# Payload Models — Client → Brain
# ─────────────────────────────────────────────

class AudioChunkPayload(BaseModel):
    """Streaming audio from client to brain."""
    encoding: str = "opus"
    sample_rate: int = 16000
    channels: int = 1
    chunk_index: int = 0
    is_final: bool = False
    data_b64: str = ""


class TextCommandPayload(BaseModel):
    """Text input (for web/CLI clients that type instead of speak)."""
    text: str
    context: Optional[dict] = None


class BiometricPayload(BaseModel):
    """Sensor data from glasses or phone."""
    heart_rate_bpm: Optional[int] = None
    spo2_pct: Optional[int] = None
    accel_xyz: Optional[list[float]] = None
    temperature_c: Optional[float] = None
    uv_index: Optional[int] = None
    gps: Optional[dict] = None  # {"lat": float, "lon": float}
    inferred_state: Optional[str] = None  # "resting", "walking", "running", "stressed"


class UIEventPayload(BaseModel):
    """User interacted with a generated UI element."""
    screen_id: str
    event: Literal["tap", "toggle", "slider", "text_input", "dismiss"]
    action_id: str
    value: Optional[Any] = None


# ─────────────────────────────────────────────
# Payload Models — Brain → Client
# ─────────────────────────────────────────────

class TranscriptPayload(BaseModel):
    """Speech-to-text result."""
    text: str
    is_partial: bool = False
    confidence: float = 1.0


class SDUIPayload(BaseModel):
    """Server-Driven UI — the generated interface."""
    screen_id: str = Field(default_factory=lambda: str(uuid4()))
    ttl_seconds: int = 300
    root: dict  # The SDUI tree (see genui/schema/)


class SDUIPatchPayload(BaseModel):
    """Partial update to an existing generated screen."""
    screen_id: str
    patches: list[dict]  # [{"path": "children.0.value", "op": "replace", "value": "new text"}]


class TTSChunkPayload(BaseModel):
    """Streaming audio from brain to client (text-to-speech)."""
    chunk_index: int = 0
    encoding: str = "mp3"
    data_b64: str = ""
    is_final: bool = False


class TextResponsePayload(BaseModel):
    """Plain text response (for CLI/chat clients)."""
    text: str
    tool_calls: Optional[list[dict]] = None


class StreamDeltaPayload(BaseModel):
    """Streaming text token from brain to client (real-time LLM output)."""
    delta: str
    stream_id: str = ""
    is_final: bool = False


class GesturePayload(BaseModel):
    """Gesture detected by a hardware daemon (glasses IMU, camera, etc.)."""
    gesture: str  # "nod", "shake", "look_up", "look_down", "double_tap"
    confidence: float = 1.0
    source: str = "imu"  # "imu", "camera", "touch"


class ErrorPayload(BaseModel):
    """Something went wrong."""
    code: str
    message: str
    recoverable: bool = True


# ─────────────────────────────────────────────
# Payload Models — Brain ↔ Daemon
# ─────────────────────────────────────────────

class NodeRegisterPayload(BaseModel):
    """Daemon announces itself to the brain."""
    node_id: str
    node_type: Literal["desktop", "server", "rpi", "robot", "glasses", "phone", "actuator", "sensor"]
    os: str = ""
    platform: str = ""  # "ios", "android", "linux", "macos"
    capabilities: list[str] = []  # ["applescript", "keyboard", "filesystem", "camera", "gpio"]


class ExecuteCommandPayload(BaseModel):
    """Brain tells daemon to do something."""
    command_id: str = Field(default_factory=lambda: str(uuid4()))
    executor: str  # "applescript", "shell", "keyboard", "gpio"
    action: str  # The actual command/script
    args: dict = Field(default_factory=dict)
    timeout_ms: int = 5000
    requires_confirmation: bool = False


class ExecuteResultPayload(BaseModel):
    """Daemon reports back the result."""
    command_id: str
    status: Literal["success", "failure", "denied", "timeout"]
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


# ─────────────────────────────────────────────
# Payload Models — Vision Pipeline (Daemon ↔ Brain)
# ─────────────────────────────────────────────

class VisionFramePayload(BaseModel):
    """Daemon pushes a captured camera frame to the brain."""
    node_id: str
    frame_id: str = Field(default_factory=lambda: str(uuid4()))
    encoding: Literal["jpeg", "png", "webp"] = "jpeg"
    resolution: list[int] = Field(default_factory=lambda: [640, 480])  # [width, height]
    data_b64: str = ""
    timestamp: float = Field(default_factory=time)
    metadata: dict = Field(default_factory=dict)  # scene_brightness, faces_detected, etc.


class VisionRequestPayload(BaseModel):
    """Brain requests a frame capture from a daemon's camera."""
    resolution: str = "640x480"
    quality: int = 80  # JPEG quality 1-100
    reason: str = ""


# ─────────────────────────────────────────────
# Payload Models — Device Registration
# ─────────────────────────────────────────────

class DeviceRegisterPayload(BaseModel):
    """Hardware device (glasses, robot, etc.) registers with the brain."""
    device_id: str
    device_type: Literal["glasses", "phone", "watch", "robot", "camera", "sensor_hub"]
    name: str = ""
    sensors: list[str] = []  # ["heart_rate", "spo2", "accelerometer", "uv", "temperature", "camera"]
    firmware_version: str = ""
    battery_pct: Optional[int] = None


# ─────────────────────────────────────────────
# Payload Models — Phone Bridge (iOS/Android → Brain)
# ─────────────────────────────────────────────

class SensorTelemetryPayload(BaseModel):
    """Single sensor reading from FERAL glasses via phone bridge."""
    node_id: str
    sensor: str  # "heart_rate", "spo2", "temperature", "uv", "steps"
    data: dict  # Sensor-specific values
    timestamp: str = ""
    source: str = "feral_glasses"


class SensorBatchPayload(BaseModel):
    """Multiple sensor readings in one message."""
    node_id: str
    readings: dict  # {"heart_rate": {...}, "spo2": {...}, ...}
    timestamp: str = ""
    source: str = "feral_glasses"


class GlassesStatusPayload(BaseModel):
    """Phone reports glasses connection status."""
    node_id: str
    glasses_connected: bool = False
    battery_level: int = -1
    glasses_model: str = "FERAL"


class SkillApprovalPayload(BaseModel):
    """User approved/rejected a proposed skill."""
    skill_id: str
    approved: bool = False


class ConfirmationResponsePayload(BaseModel):
    """User responded to a permission confirmation."""
    action: str
    approved: bool = False


class PermissionRequestPayload(BaseModel):
    """Agent requests folder access from the user."""
    request_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    path: str
    operation: Literal["read", "write", "readwrite"] = "read"
    reason: str = ""


class PermissionResponsePayload(BaseModel):
    """User grants or denies folder access."""
    request_id: str
    granted: bool = False
    mode: str = "read"


# ─────────────────────────────────────────────
# Payload Models — Voice Pipeline
# ─────────────────────────────────────────────

class VoiceConfigPayload(BaseModel):
    """Client/node declares voice capabilities and selected mode."""
    node_id: str = ""
    supports_realtime: bool = False
    mode: Literal["realtime", "whisper", "auto", "disabled"] = "auto"
    preferred_model: str = ""
    sample_rate: int = 24000
    encoding: str = "pcm16"

class AudioResponsePayload(BaseModel):
    """Brain sends audio back to a node (realtime TTS or Whisper TTS)."""
    data_b64: str = ""
    encoding: str = "pcm16"
    sample_rate: int = 24000
    is_final: bool = False

class VisionQueryPayload(BaseModel):
    """User explicitly asks about what the camera sees."""
    query: str = "What do you see?"
    node_id: str = ""
    force: bool = True


class HandoffRequestPayload(BaseModel):
    """Client asks to move working-memory context to another device class."""
    to_node_type: str = "desktop"
    history_depth: int = Field(default=20, ge=1, le=500)


# ─────────────────────────────────────────────
# Message Type Registry — Maps type strings to payload models
# ─────────────────────────────────────────────

MESSAGE_TYPES = {
    # Client → Brain
    "audio_chunk": AudioChunkPayload,
    "text_command": TextCommandPayload,
    "biometric": BiometricPayload,
    "ui_event": UIEventPayload,
    "device_register": DeviceRegisterPayload,
    "handoff_request": HandoffRequestPayload,

    # Brain → Client
    "transcript": TranscriptPayload,
    "sdui": SDUIPayload,
    "sdui_patch": SDUIPatchPayload,
    "tts_chunk": TTSChunkPayload,
    "text_response": TextResponsePayload,
    "stream_delta": StreamDeltaPayload,
    "gesture": GesturePayload,
    "error": ErrorPayload,

    # Brain ↔ Daemon / Phone Bridge
    "register": NodeRegisterPayload,
    "node_register": NodeRegisterPayload,
    "execute": ExecuteCommandPayload,
    "execute_result": ExecuteResultPayload,

    # Vision Pipeline
    "vision_frame": VisionFramePayload,
    "vision_request": VisionRequestPayload,

    # Phone Bridge
    "sensor_telemetry": SensorTelemetryPayload,
    "sensor_batch": SensorBatchPayload,
    "glasses_status": GlassesStatusPayload,
    "skill_approval": SkillApprovalPayload,
    "confirmation_response": ConfirmationResponsePayload,
    "permission_request": PermissionRequestPayload,
    "permission_response": PermissionResponsePayload,

    # Voice Pipeline
    "voice_config": VoiceConfigPayload,
    "audio_response": AudioResponsePayload,
    "vision_query": VisionQueryPayload,
}


def parse_message(raw: dict) -> tuple[FeralMessage, BaseModel | None]:
    """Parse a raw dict into a FeralMessage + typed payload."""
    msg = FeralMessage(**raw)
    payload_cls = MESSAGE_TYPES.get(msg.type)
    if payload_cls:
        return msg, payload_cls(**msg.payload)
    return msg, None
