"""Canonical HUP v1 capability vocabulary.

Mirrors the enum in `HUP_SPEC.md` §5.1 exactly. Exposed both as module-level
constants (`capability.HEART_RATE`) for ergonomic daemon code and as a
string-valued Enum (`Capability`) for programmatic iteration/validation.
"""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    HEART_RATE = "heart_rate"
    SPO2 = "spo2"
    TEMPERATURE = "temperature"
    UV = "uv"
    ACCELEROMETER = "accelerometer"
    GYROSCOPE = "gyroscope"
    AMBIENT_LIGHT = "ambient_light"
    STEPS = "steps"
    BATTERY = "battery"
    GPS = "gps"
    MICROPHONE = "microphone"
    CAMERA = "camera"
    DISPLAY = "display"
    SPEAKER = "speaker"
    HAPTIC = "haptic"
    BUZZER = "buzzer"
    LED = "led"
    MOTOR = "motor"
    RELAY = "relay"
    VALVE = "valve"
    KEYBOARD = "keyboard"
    APPLESCRIPT = "applescript"
    FILESYSTEM = "filesystem"
    GPIO = "gpio"
    SHELL = "shell"
    TELEMETRY = "telemetry"
    PASSIVE_SENSOR = "passive_sensor"
    ACTIVE_ACTUATOR = "active_actuator"


HEART_RATE = Capability.HEART_RATE
SPO2 = Capability.SPO2
TEMPERATURE = Capability.TEMPERATURE
UV = Capability.UV
ACCELEROMETER = Capability.ACCELEROMETER
GYROSCOPE = Capability.GYROSCOPE
AMBIENT_LIGHT = Capability.AMBIENT_LIGHT
STEPS = Capability.STEPS
BATTERY = Capability.BATTERY
GPS = Capability.GPS
MICROPHONE = Capability.MICROPHONE
CAMERA = Capability.CAMERA
DISPLAY = Capability.DISPLAY
SPEAKER = Capability.SPEAKER
HAPTIC = Capability.HAPTIC
BUZZER = Capability.BUZZER
LED = Capability.LED
MOTOR = Capability.MOTOR
RELAY = Capability.RELAY
VALVE = Capability.VALVE
KEYBOARD = Capability.KEYBOARD
APPLESCRIPT = Capability.APPLESCRIPT
FILESYSTEM = Capability.FILESYSTEM
GPIO = Capability.GPIO
SHELL = Capability.SHELL
TELEMETRY = Capability.TELEMETRY
PASSIVE_SENSOR = Capability.PASSIVE_SENSOR
ACTIVE_ACTUATOR = Capability.ACTIVE_ACTUATOR


TIER_MAP: dict[Capability, str] = {
    Capability.HEART_RATE: "passive_sensor",
    Capability.SPO2: "passive_sensor",
    Capability.TEMPERATURE: "passive_sensor",
    Capability.UV: "passive_sensor",
    Capability.ACCELEROMETER: "passive_sensor",
    Capability.GYROSCOPE: "passive_sensor",
    Capability.AMBIENT_LIGHT: "passive_sensor",
    Capability.STEPS: "passive_sensor",
    Capability.BATTERY: "passive_sensor",
    Capability.GPS: "passive_sensor",
    Capability.TELEMETRY: "passive_sensor",
    Capability.PASSIVE_SENSOR: "passive_sensor",
    Capability.CAMERA: "camera",
    Capability.MICROPHONE: "audio",
    Capability.SPEAKER: "audio",
    Capability.DISPLAY: "active_actuator",
    Capability.HAPTIC: "active_actuator",
    Capability.BUZZER: "active_actuator",
    Capability.LED: "active_actuator",
    Capability.ACTIVE_ACTUATOR: "active_actuator",
    Capability.MOTOR: "motor",
    Capability.RELAY: "motor",
    Capability.VALVE: "motor",
    Capability.KEYBOARD: "motor",
    Capability.APPLESCRIPT: "motor",
    Capability.FILESYSTEM: "motor",
    Capability.GPIO: "motor",
    Capability.SHELL: "motor",
}


def tier_for(cap: "Capability | str") -> str:
    """Return the policy tier for a capability (passive_sensor|camera|audio|active_actuator|motor)."""
    if isinstance(cap, str):
        try:
            cap = Capability(cap)
        except ValueError:
            return "unknown"
    return TIER_MAP.get(cap, "unknown")
