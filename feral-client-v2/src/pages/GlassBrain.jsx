import React, { useEffect, useState } from 'react';
import { ExternalLink, Maximize2 } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import EmptyState from '../ui/EmptyState';
import { useFeralSocket } from '../hooks/useFeralSocket';
import { apiJson } from '../lib/api';

/**
 * Glass Brain v2 — for Brain deployments that ship v1 too, we embed v1's
 * proven Three.js 3D visualiser in an iframe. Until a full v2 port lands,
 * this surface is honest about what it is: real data, real visualisation,
 * just via the sibling client.
 *
 * When v1 isn't available on the same Brain, a text-stream fallback
 * renders via useFeralSocket so the page still works.
 */
const V1_GLASS_PATH = '/?v1=1#/glass-brain';
const V1_GLASS_ROUTE = '/glass-brain';

export default function GlassBrain() {
  const socket = useFeralSocket();
  const [events, setEvents] = useState([]);
  const [v1Available, setV1Available] = useState(null);

  useEffect(() => {
    // Detect v1 availability by hitting /api/dashboard which always works;
    // the iframe target URL is on the same host.
    apiJson('/api/dashboard').then(() => setV1Available(true)).catch(() => setV1Available(false));
  }, []);

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      if (!msg || typeof msg !== 'object') return;
      setEvents((prev) => [{ id: Date.now() + Math.random(), msg }, ...prev].slice(0, 120));
    });
    return unsub;
  }, [socket]);

  const iframeSrc = typeof window !== 'undefined'
    ? `${window.location.origin}/${V1_GLASS_PATH.replace(/^\//, '')}`
    : V1_GLASS_PATH;

  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="Glass Brain"
        actions={(
          <a
            href={`/?v1=1#${V1_GLASS_ROUTE}`}
            target="_blank"
            rel="noreferrer"
            className="v2-btn"
            title="Open 3D view in new tab"
          >
            <ExternalLink size={13} /> Open 3D
          </a>
        )}
      >
        <p className="v2-p v2-p--muted">
          Live Brain topology — session nodes, skill fires, memory writes, HUP heartbeats.
          The full 3D visualisation runs inside the sibling v1 client (same Brain, same data).
        </p>
      </Pane>

      {v1Available !== false && (
        <Glass level={2} radius="lg" padding="none" className="v2-glass-brain-iframe-wrap">
          <iframe
            src={iframeSrc}
            title="Glass Brain 3D"
            className="v2-glass-brain-iframe"
            sandbox="allow-same-origin allow-scripts allow-popups"
            loading="lazy"
          />
        </Glass>
      )}

      <Pane title="Event stream">
        <p className="v2-p v2-p--muted">Every WS frame lands here in real time. Useful for debugging.</p>
        <Glass level={0} radius="md" padding="md">
          <ul className="v2-event-log">
            {events.length === 0 && <li className="v2-empty">Listening…</li>}
            {events.map(({ id, msg }) => (
              <li key={id} className="v2-event-row">
                <span className="v2-event-type">{msg.type || msg.hop || 'event'}</span>
                <span className="v2-event-body">{JSON.stringify(msg.payload || msg).slice(0, 200)}</span>
              </li>
            ))}
          </ul>
        </Glass>
      </Pane>
    </div>
  );
}
