import { useEffect, useState, useCallback } from 'react';
import { useFeralSocket } from './useFeralSocket';

/**
 * useBrainEvents — typed WS event subscription.
 *
 * Every v2 page that needs real-time badges (active skills, streaming
 * tool calls, HUP node connects, memory writes, proactive alerts) pulls
 * from this hook instead of wiring its own subscribe() handlers.
 *
 * Usage:
 *   const events = useBrainEvents({ types: ['tool_start', 'skill_result'] });
 *   const latest = events[0]; // most recent matching event
 *
 * Or with a callback:
 *   useBrainEvents({ on: (msg) => {...} });
 */
const DEFAULT_LIMIT = 50;

export function useBrainEvents({ types, on, limit = DEFAULT_LIMIT } = {}) {
  const socket = useFeralSocket();
  const [events, setEvents] = useState([]);

  const accept = useCallback(
    (msg) => {
      if (!msg || typeof msg !== 'object') return false;
      if (!types || types.length === 0) return true;
      return types.includes(msg.type) || types.includes(msg.event);
    },
    [types],
  );

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      if (!accept(msg)) return;
      if (on) {
        try { on(msg); } catch {}
      }
      setEvents((prev) => {
        const next = [{ id: Date.now() + Math.random(), msg }, ...prev];
        return next.slice(0, limit);
      });
    });
    return unsub;
  }, [socket, accept, on, limit]);

  return events;
}

export const EVENT_TYPES = {
  STREAM_DELTA: 'stream_delta',
  TEXT_RESPONSE: 'text_response',
  TOOL_START: 'tool_start',
  TOOL_RESULT: 'tool_result',
  SKILL_START: 'skill_start',
  SKILL_RESULT: 'skill_result',
  SKILL_PROPOSAL: 'skill_proposal',
  MEMORY_WRITE: 'memory_write',
  HUP_CONNECT: 'hup_connect',
  HUP_DISCONNECT: 'hup_disconnect',
  NODE_HEARTBEAT: 'node_heartbeat',
  CHANNEL_IN: 'channel_in',
  CHANNEL_OUT: 'channel_out',
  PROACTIVE: 'proactive',
  STATE_PUSH: 'state_push',
  BRAIN_EVENT: 'brain_event',
  SDUI: 'sdui',
  SDUI_RENDER: 'sdui_render',
  GENUI_RENDER: 'genui_render',
  TRANSCRIPT: 'transcript',
  PERMISSION_REQUEST: 'permission_request',
  CAPABILITY_LEARNED: 'capability_learned',
};
