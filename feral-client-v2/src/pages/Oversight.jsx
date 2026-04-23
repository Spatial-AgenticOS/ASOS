/**
 * Oversight — live supervisor-event river.
 *
 * Reads GET /api/supervisor/events every 4 s, mounts a live WS
 * subscriber for `supervisor_event` frames so new rows land instantly,
 * and exposes the kill switch (POST /api/supervisor/pause).
 *
 * Filters: source (web / node / voice / cron / channel / proactive /
 * twin / …), actor (user / twin / system), decision (allowed / denied /
 * queued / error).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Pause, Play, Shield, Clock, Filter } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import EmptyState from '../ui/EmptyState';
import StatusDot from '../ui/StatusDot';
import { useFeralSocket } from '../hooks/useFeralSocket';
import { apiJson, apiFetch } from '../lib/api';

const SOURCE_OPTIONS = ['', 'web', 'voice', 'node', 'cron', 'channel', 'proactive', 'twin', 'ui'];
const DECISION_OPTIONS = ['', 'allowed', 'denied', 'queued', 'error'];

const DECISION_TONE = {
  allowed: 'live',
  denied: 'error',
  queued: 'warn',
  error: 'error',
};

function relativeTime(ts) {
  if (!ts) return '—';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.max(0, Math.round(diff))}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

export default function Oversight() {
  const socket = useFeralSocket();
  const [events, setEvents] = useState([]);
  const [stats, setStats] = useState(null);
  const [filters, setFilters] = useState({ source: '', decision: '', actor: '' });
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', '80');
      if (filters.source) params.set('source', filters.source);
      if (filters.decision) params.set('decision', filters.decision);
      if (filters.actor) params.set('actor', filters.actor);
      const d = await apiJson(`/api/supervisor/events?${params.toString()}`);
      setEvents(d?.events || []);
      const s = await apiJson('/api/supervisor/stats').catch(() => null);
      if (s) {
        setStats(s);
        setPaused(!!s.paused);
      }
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      if (!msg || msg.type !== 'supervisor_event') return;
      const payload = msg.payload || msg;
      setEvents((prev) => [{ ...payload }, ...prev].slice(0, 200));
    });
    return unsub;
  }, [socket]);

  const togglePause = async () => {
    const next = !paused;
    setPaused(next);
    await apiFetch('/api/supervisor/pause', {
      method: 'POST',
      body: JSON.stringify({ paused: next }),
    });
    refresh();
  };

  const filtered = useMemo(() => {
    if (!filters.source && !filters.decision && !filters.actor) return events;
    return events.filter((e) => (
      (!filters.source || e.source === filters.source)
      && (!filters.decision || e.decision === filters.decision)
      && (!filters.actor || e.actor === filters.actor)
    ));
  }, [events, filters]);

  return (
    <div className="v2-page v2-page--stack v2-oversight" data-testid="v2-marker">
      <Pane
        title="Oversight"
        actions={(
          <>
            <button
              type="button"
              className={`v2-btn${paused ? ' v2-btn--primary' : ' v2-btn--ghost'}`}
              onClick={togglePause}
              title="Pause every orchestrator call — the kill switch."
            >
              {paused ? <><Play size={13} /> Resume</> : <><Pause size={13} /> Pause actions</>}
            </button>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh} aria-label="Refresh">
              <RefreshCw size={13} />
            </button>
          </>
        )}
      >
        <p className="v2-p v2-p--muted">
          Every command the Brain acts on passes through the Supervisor.
          Web chat, voice, HUP nodes, cron, channels, proactive alerts,
          and the digital twin all land here as audit rows. Use Pause to
          halt every outgoing action immediately.
        </p>

        <div className="v2-oversight-stats">
          <StatPill label="Total" value={stats?.total ?? '—'} />
          <StatPill label="Paused" value={paused ? 'yes' : 'no'} tone={paused ? 'warn' : 'live'} />
          {stats?.by_source && Object.entries(stats.by_source).slice(0, 6).map(([src, n]) => (
            <StatPill key={src} label={src} value={n} />
          ))}
        </div>

        <div className="v2-oversight-filters">
          <Filter size={13} aria-hidden="true" />
          <Select
            label="source"
            value={filters.source}
            onChange={(v) => setFilters((f) => ({ ...f, source: v }))}
            options={SOURCE_OPTIONS}
          />
          <Select
            label="decision"
            value={filters.decision}
            onChange={(v) => setFilters((f) => ({ ...f, decision: v }))}
            options={DECISION_OPTIONS}
          />
          <input
            className="v2-input"
            style={{ minWidth: 120 }}
            placeholder="actor (user / twin / system)"
            value={filters.actor}
            onChange={(e) => setFilters((f) => ({ ...f, actor: e.target.value }))}
          />
        </div>
      </Pane>

      <Pane title={`Events · ${filtered.length}`}>
        {loading && filtered.length === 0 && <EmptyState title="Loading…" />}
        {!loading && filtered.length === 0 && (
          <EmptyState title="No events match this filter" />
        )}
        <ul className="v2-oversight-list">
          {filtered.map((ev) => (
            <li key={ev.event_id} className="v2-oversight-row">
              <Glass level={0} radius="md" padding="sm">
                <div className="v2-oversight-row-head">
                  <StatusDot tone={DECISION_TONE[ev.decision] || 'neutral'} />
                  <span className="v2-chip v2-chip--muted">{ev.source}</span>
                  <span className="v2-chip v2-chip--muted">{ev.kind}</span>
                  <span className="v2-chip v2-chip--muted" title={ev.actor}>by {ev.actor}</span>
                  <span className="v2-chip v2-chip--muted"><Clock size={10} /> {relativeTime(ev.ts)}</span>
                  <span className="v2-chip v2-chip--muted">{ev.latency_ms}ms</span>
                  <span className="v2-oversight-spacer" />
                  <span
                    className={`v2-chip v2-chip--${DECISION_TONE[ev.decision] === 'live' ? 'live' : DECISION_TONE[ev.decision] === 'error' ? 'error' : 'warn'}`}
                  >
                    {ev.decision}
                  </span>
                </div>
                <div className="v2-oversight-row-body">
                  <Shield size={11} aria-hidden="true" />
                  <code>{ev.payload_summary || '—'}</code>
                </div>
                <div className="v2-oversight-row-meta">
                  session {(ev.session_id || '').slice(0, 8) || '—'} · hash {ev.payload_hash}
                </div>
              </Glass>
            </li>
          ))}
        </ul>
      </Pane>
    </div>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <label className="v2-oversight-select">
      <span>{label}</span>
      <select className="v2-input" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>{o || 'any'}</option>
        ))}
      </select>
    </label>
  );
}

function StatPill({ label, value, tone }) {
  return (
    <Glass level={0} radius="md" padding="sm" className="v2-oversight-stat">
      <div className="v2-stat-label">{label}</div>
      <div className={`v2-stat-value${tone ? ` is-${tone}` : ''}`}>{value}</div>
    </Glass>
  );
}
