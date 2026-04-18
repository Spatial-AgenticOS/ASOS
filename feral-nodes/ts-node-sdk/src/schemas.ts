/*
 * Zod mirrors of the HUP v1 wire schemas from ../../HUP_SPEC.md §5.
 * These validate outbound frames before send so daemons are conformant by construction.
 */

import { z } from "zod";

export const HUP_VERSION = "1.0.0";

export const NodeType = z.enum([
  "desktop",
  "server",
  "rpi",
  "robot",
  "glasses",
  "phone",
  "actuator",
  "sensor",
  "wearable",
  "camera",
  "vehicle",
  "appliance",
]);
export type NodeType = z.infer<typeof NodeType>;

export const NodeRegisterPayload = z.object({
  node_id: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
  node_type: NodeType.default("sensor"),
  name: z.string().default(""),
  manufacturer: z.string().default(""),
  model: z.string().default(""),
  firmware_version: z.string().default(""),
  platform: z.string().default(""),
  os: z.string().default(""),
  capabilities: z.array(z.string()).default([]),
  sensors: z.array(z.string()).default([]),
  actuators: z.array(z.string()).default([]),
  location: z.string().default(""),
  tags: z.array(z.string()).default([]),
});
export type NodeRegisterPayload = z.infer<typeof NodeRegisterPayload>;

export const NodeAckPayload = z.object({
  node_id: z.string(),
  session_token: z.string(),
  heartbeat_ms: z.number().int().default(10_000),
  server_time: z.number().default(() => Date.now() / 1000),
  granted_capabilities: z.array(z.string()).default([]),
  denied_capabilities: z.array(z.string()).default([]),
});
export type NodeAckPayload = z.infer<typeof NodeAckPayload>;

export const NodeHeartbeatPayload = z.object({
  ts: z.number().default(() => Date.now() / 1000),
  battery_pct: z.number().int().min(0).max(100).nullable().optional(),
  rssi: z.number().int().nullable().optional(),
});
export type NodeHeartbeatPayload = z.infer<typeof NodeHeartbeatPayload>;

export const DeviceEventPayload = z.object({
  node_id: z.string(),
  event_type: z.string(),
  data: z.record(z.any()).default({}),
  ts: z.number().default(() => Date.now() / 1000),
});
export type DeviceEventPayload = z.infer<typeof DeviceEventPayload>;

export const HUPActionRequestPayload = z.object({
  action_id: z.string().min(1).max(64),
  name: z.string().min(1).max(64),
  params: z.record(z.any()).default({}),
  timeout_ms: z.number().int().min(1).max(120_000).default(5000),
  requires_confirmation: z.boolean().default(false),
});
export type HUPActionRequestPayload = z.infer<typeof HUPActionRequestPayload>;

export const HUPActionResponsePayload = z.object({
  action_id: z.string(),
  success: z.boolean(),
  result: z.record(z.any()).default({}),
  error: z.string().nullable().optional(),
  duration_ms: z.number().int().min(0).default(0),
});
export type HUPActionResponsePayload = z.infer<typeof HUPActionResponsePayload>;

export const NodeByePayload = z.object({
  reason: z.string().default("shutdown"),
  restart_in_s: z.number().int().default(0),
});
export type NodeByePayload = z.infer<typeof NodeByePayload>;

export const ErrorPayload = z.object({
  code: z.number().int(),
  name: z.string(),
  message: z.string(),
  recoverable: z.boolean().default(true),
  ref_action_id: z.string().nullable().optional(),
});
export type ErrorPayload = z.infer<typeof ErrorPayload>;

export const HUPMessageType = z.enum([
  "node_register",
  "node_ack",
  "node_heartbeat",
  "device_event",
  "hup_action_request",
  "hup_action_response",
  "node_bye",
  "error",
]);
export type HUPMessageType = z.infer<typeof HUPMessageType>;

const SCHEMAS: Record<string, z.ZodTypeAny> = {
  node_register: NodeRegisterPayload,
  node_ack: NodeAckPayload,
  node_heartbeat: NodeHeartbeatPayload,
  device_event: DeviceEventPayload,
  hup_action_request: HUPActionRequestPayload,
  hup_action_response: HUPActionResponsePayload,
  node_bye: NodeByePayload,
  error: ErrorPayload,
};

export interface HUPFrame {
  hup_version: string;
  type: string;
  ts: number;
  payload: Record<string, unknown>;
}

export function buildFrame(
  type: string,
  payload: Record<string, unknown>,
): HUPFrame {
  const schema = SCHEMAS[type];
  if (!schema) {
    throw new Error(`unknown HUP message type: ${type}`);
  }
  const parsed = schema.parse(payload) as Record<string, unknown>;
  return {
    hup_version: HUP_VERSION,
    type,
    ts: Date.now() / 1000,
    payload: parsed,
  };
}
