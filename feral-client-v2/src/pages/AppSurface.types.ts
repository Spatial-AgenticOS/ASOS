/**
 * Mirror of feral-core/genui/app_message_schema.py.
 *
 * Keep in lockstep with the Python module — there's a comment in
 * both halves reminding maintainers. The Python side is the
 * authoritative schema for backend parsers; this TS half is what
 * runs on the host (FERAL client) to drop malformed iframe→host
 * postMessage events before they reach the FERAL reducer.
 */

export const APP_MESSAGE_TYPES = [
  'request_data',
  'submit_form',
  'navigate',
  'close',
] as const;

export type AppMessageType = (typeof APP_MESSAGE_TYPES)[number];

export interface AppMessage {
  type: AppMessageType;
  payload: Record<string, unknown>;
  message_id: string;
  signed_with_key_id: string;
}

export const MAX_PAYLOAD_BYTES = 64 * 1024;

const MAX_ID_LENGTH = 128;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return Boolean(v) && typeof v === 'object' && !Array.isArray(v);
}

function isAllowedType(v: unknown): v is AppMessageType {
  return typeof v === 'string' && (APP_MESSAGE_TYPES as readonly string[]).includes(v);
}

/**
 * Validate an inbound postMessage payload against the strict
 * AppMessage shape. Returns the typed message on success, or
 * `null` for any malformed input. NEVER throws — the host's
 * `window.message` listener uses this as a guard to drop bad
 * events without crashing the message loop.
 */
export function validateAppMessage(raw: unknown): AppMessage | null {
  if (!isPlainObject(raw)) return null;

  const { type, payload, message_id, signed_with_key_id } = raw as Record<string, unknown>;

  if (!isAllowedType(type)) return null;
  if (!isPlainObject(payload)) return null;
  if (typeof message_id !== 'string' || !message_id || message_id.length > MAX_ID_LENGTH) {
    return null;
  }
  if (
    typeof signed_with_key_id !== 'string'
    || !signed_with_key_id
    || signed_with_key_id.length > MAX_ID_LENGTH
  ) {
    return null;
  }

  let serialised: string;
  try {
    serialised = JSON.stringify(payload);
  } catch {
    return null;
  }
  if (serialised.length > MAX_PAYLOAD_BYTES) return null;

  // Reject unknown top-level keys to mirror Python's `extra="forbid"`.
  const allowedKeys = new Set(['type', 'payload', 'message_id', 'signed_with_key_id']);
  for (const key of Object.keys(raw as Record<string, unknown>)) {
    if (!allowedKeys.has(key)) return null;
  }

  return {
    type,
    payload: payload as Record<string, unknown>,
    message_id,
    signed_with_key_id,
  };
}
