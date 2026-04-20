import React, { useEffect, useState } from 'react';
import { useFeralSocket } from '../hooks/useFeralSocket';

/**
 * LiveOpsStream — faint flow of Brain events: skill fires, HUP node
 * connect/disconnect, memory writes, channel traffic, Tool Genesis drafts.
 * Low contrast, readable if you focus, invisible if you don't.
 */
const MAX_EVENTS = 14;
const TYPE_LABEL = {
  skill_start: 'skill',
  skill_end: 'skill',
  tool_call: 'tool',
  tool_result: 'tool',
  memory_write: 'mem',
  hup_connect: 'node',
  hup_disconnect: 'node',
  node_heartbeat: 'node',
  channel_in: 'chan',
  channel_out: 'chan',
  tool_genesis_draft: 'forge',
  tool_genesis_promote: 'forge',
  proactive: 'alert',
};

function summarise(ev) {
  if (!ev || typeof ev !== 'object') return { kind: 'log', text: String(ev ?? '') };
  const type = ev.type || ev.event || 'event';
  const kind = TYPE_LABEL[type] || 'event';
  const subject = ev.skill_id || ev.node_id || ev.channel_id || ev.name || ev.subject || '';
  const verb = type.replace(/_/g, ' ');
  const text = subject ? `${verb} · ${subject}` : verb;
  return { kind, text };
}

export default function LiveOpsStream({ active }) {
  const socket = useFeralSocket();
  const [events, setEvents] = useState([]);

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      const hop = msg?.hop;
      if (hop !== 'brain' && hop !== 'system') return;
      const next = summarise(msg);
      setEvents((prev) => {
        const trimmed = [{ id: Date.now() + Math.random(), ...next }, ...prev];
        return trimmed.slice(0, MAX_EVENTS);
      });
    });
    return unsub;
  }, [socket]);

  return (
    <ul
      className={`v2-liveops${active ? ' is-active' : ''}`}
      aria-hidden="true"
    >
      {events.map((e) => (
        <li key={e.id} className="v2-liveops-row">
          <span className={`v2-liveops-tag v2-liveops-tag--${e.kind}`}>{e.kind}</span>
          <span className="v2-liveops-text">{e.text}</span>
        </li>
      ))}
    </ul>
  );
}
