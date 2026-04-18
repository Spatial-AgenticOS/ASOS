/*
 * Canonical HUP v1 capability vocabulary for the TypeScript SDK.
 * Mirrors feral-nodes/HUP_SPEC.md §5.1 and the Python SDK's capability.py.
 */

export const Capability = {
  HEART_RATE: "heart_rate",
  SPO2: "spo2",
  TEMPERATURE: "temperature",
  UV: "uv",
  ACCELEROMETER: "accelerometer",
  GYROSCOPE: "gyroscope",
  AMBIENT_LIGHT: "ambient_light",
  STEPS: "steps",
  BATTERY: "battery",
  GPS: "gps",
  MICROPHONE: "microphone",
  CAMERA: "camera",
  DISPLAY: "display",
  SPEAKER: "speaker",
  HAPTIC: "haptic",
  BUZZER: "buzzer",
  LED: "led",
  MOTOR: "motor",
  RELAY: "relay",
  VALVE: "valve",
  KEYBOARD: "keyboard",
  APPLESCRIPT: "applescript",
  FILESYSTEM: "filesystem",
  GPIO: "gpio",
  SHELL: "shell",
  TELEMETRY: "telemetry",
  PASSIVE_SENSOR: "passive_sensor",
  ACTIVE_ACTUATOR: "active_actuator",
} as const;

export type CapabilityName = (typeof Capability)[keyof typeof Capability];

const TIERS: Record<string, string> = {
  heart_rate: "passive_sensor",
  spo2: "passive_sensor",
  temperature: "passive_sensor",
  uv: "passive_sensor",
  accelerometer: "passive_sensor",
  gyroscope: "passive_sensor",
  ambient_light: "passive_sensor",
  steps: "passive_sensor",
  battery: "passive_sensor",
  gps: "passive_sensor",
  telemetry: "passive_sensor",
  passive_sensor: "passive_sensor",
  camera: "camera",
  microphone: "audio",
  speaker: "audio",
  display: "active_actuator",
  haptic: "active_actuator",
  buzzer: "active_actuator",
  led: "active_actuator",
  active_actuator: "active_actuator",
  motor: "motor",
  relay: "motor",
  valve: "motor",
  keyboard: "motor",
  applescript: "motor",
  filesystem: "motor",
  gpio: "motor",
  shell: "motor",
};

export function tierFor(cap: string): string {
  return TIERS[cap] ?? "unknown";
}
