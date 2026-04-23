import React, { useEffect, useMemo, useState } from 'react';
import { Activity, Cpu, Layers, RefreshCw, Radio, Zap } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import ConsciousnessMindMap from '../components/ConsciousnessMindMap';
import { useFeralSocket } from '../hooks/useFeralSocket';
import { apiJson } from '../lib/api';

/**
 * Glass Brain v2 — a live, introspective view of everything alive inside
 * FERAL right now. No iframes, no v1 embeds. One pure native surface:
 *   • system vitals (brain / sessions / skills / devices / load)
 *   • consciousness mind-map of every in-flight ConsciousnessEntity
 *   • entity kind legend with live counts
 *   • raw event stream (WS frames) for debugging
 */

const KIND_LABELS = {
  intent: 'Intents',
  flow: 'Flows',
  thought: 'Thoughts',
  device_stream: 'Device streams',
  turn: 'Turns',
};

const KIND_DOT = {
  intent: 'var(--v2-state-live)',
  flow: 'var(--v2-text-primary)',
  thought: 'var(--v2-state-warn)',
  device_stream: 'var(--v2-state-live)',
  turn: 'var(--v2-text-secondary)',
};

export default function GlassBrain() {
  const socket = useFeralSocket();
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState({ total: 0, byKind: {}, byStatus: {} });
  const [dashboard, setDashboard] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      if (!msg || typeof msg !== 'object') return;
      setEvents((prev) => [{ id: Date.now() + Math.random(), msg }, ...prev].slice(0, 120));
    });
    return unsub;
  }, [socket]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [cons, dash] = await Promise.all([
          apiJson('/api/consciousness/state?include_abandoned=false').catch(() => null),
          apiJson('/api/dashboard').catch(() => null),
        ]);
        if (cancelled) return;
        if (cons && Array.isArray(cons.entities)) {
          const byKind = {};
          const byStatus = {};
          for (const e of cons.entities) {
            byKind[e.kind] = (byKind[e.kind] || 0) + 1;
            byStatus[e.status] = (byStatus[e.status] || 0) + 1;
          }
          setSummary({ total: cons.entities.length, byKind, byStatus });
        }
        if (dash) setDashboard(dash);
      } catch { /* ignore */ }
    }
    load();
    const id = setInterval(load, 8000);
    return () => { cancelled = true; clearInterval(id); };
  }, [refreshKey]);

  const vitals = useMemo(() => {
    const d = dashboard || {};
    return [
      { icon: Cpu, label: 'Brain', value: d.health?.status === 'ok' ? 'online' : (d.health?.status || '—'), tone: d.health?.status === 'ok' ? 'live' : 'muted' },
      { icon: Activity, label: 'In-flight', value: summary.total, tone: summary.total > 0 ? 'live' : 'muted' },
      { icon: Layers, label: 'Sessions', value: d.session_count ?? '—' },
      { icon: Radio, label: 'Devices', value: d.device_count ?? '—' },
      { icon: Zap, label: 'Skills', value: d.health?.skills?.count ?? '—' },
    ];
  }, [dashboard, summary]);

  const kindRows = useMemo(
    () => Object.keys(KIND_LABELS)
      .map((k) => ({ kind: k, label: KIND_LABELS[k], count: summary.byKind[k] || 0 }))
      .filter((r) => r.count > 0 || r.kind === 'intent' || r.kind === 'flow'),
    [summary],
  );

  return (
    <div className="v2-page v2-page--stack v2-glass-brain" data-testid="v2-marker">
      <Pane
        title="Glass Brain"
        actions={(
          <button
            type="button"
            className="v2-btn"
            onClick={() => setRefreshKey((k) => k + 1)}
            title="Refresh"
          >
            <RefreshCw size={13} /> Refresh
          </button>
        )}
      >
        <p className="v2-p v2-p--muted">
          A window into the agent's operational self-model. Every node is a live
          <em> ConsciousnessEntity</em> — an intent, flow, paused thought, or device stream
          FERAL is currently aware of. Edges connect them to the session, skill, or device
          that owns them. Nothing here is mocked; it all comes from the consciousness store
          and WebSocket event bus in real time.
        </p>

        <div className="v2-glass-brain-vitals">
          {vitals.map(({ icon: Icon, label, value, tone }) => (
            <Glass key={label} level={1} radius="md" padding="sm" className="v2-glass-brain-vital">
              <div className="v2-glass-brain-vital-icon"><Icon size={14} /></div>
              <div className="v2-glass-brain-vital-text">
                <div className="v2-glass-brain-vital-label">{label}</div>
                <div className={`v2-glass-brain-vital-value${tone ? ` is-${tone}` : ''}`}>{value}</div>
              </div>
            </Glass>
          ))}
        </div>
      </Pane>

      <Pane
        title="Consciousness mind-map"
        actions={(
          <div className="v2-glass-brain-legend" aria-label="Entity legend">
            {kindRows.map(({ kind, label, count }) => (
              <span key={kind} className="v2-glass-brain-legend-row" title={`${count} ${label.toLowerCase()} in flight`}>
                <span
                  className="v2-glass-brain-legend-dot"
                  style={{ background: KIND_DOT[kind] || 'var(--v2-text-tertiary)' }}
                  aria-hidden="true"
                />
                <span className="v2-glass-brain-legend-label">{label}</span>
                <span className="v2-glass-brain-legend-count">{count}</span>
              </span>
            ))}
          </div>
        )}
      >
        <ConsciousnessMindMap />
      </Pane>

      <Pane title="Event stream">
        <p className="v2-p v2-p--muted">
          Every WebSocket frame emitted by the Brain lands here in real time.
          Useful for debugging flow state and agent handoffs.
        </p>
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
