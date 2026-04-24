/**
 * Memory Context Inspector — shows what the Brain's multi-memory stack
 * actually surfaced for the last N LLM turns.
 *
 * Every system-prompt assembly records a snapshot:
 *   { session_id, query, memory_filter, memory_context, latency_ms, ts }
 *
 * This page reads the snapshot ring over `GET /api/memory/context?limit=`
 * and renders each as a collapsible card. Its whole point is to prove to
 * the user that knowledge-graph + episode search + working context are
 * firing on every turn — not just "recent messages".
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Clock, Tag, Brain } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import EmptyState from '../ui/EmptyState';
import BackButton from '../ui/BackButton';
import { apiJson } from '../lib/api';

function relativeTime(ts) {
  if (!ts) return '—';
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return `${Math.max(0, Math.round(diff))}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function MemoryBlock({ content }) {
  // Split on the `## Heading` markers the backend uses so we can render
  // each tier as a titled block instead of one blob.
  const parts = useMemo(() => {
    if (!content) return [];
    const chunks = content.split(/\n(?=## )/g).filter((s) => s.trim().length > 0);
    return chunks.map((chunk) => {
      const match = chunk.match(/^##\s*(.+?)\n([\s\S]*)$/);
      if (!match) return { title: 'Memory', body: chunk };
      return { title: match[1].trim(), body: match[2].trim() };
    });
  }, [content]);

  if (!parts.length) {
    return (
      <p className="v2-p v2-p--muted v2-p--tiny" style={{ marginTop: 4 }}>
        The builder returned nothing — working memory empty, KG/episodes missed.
      </p>
    );
  }

  return (
    <div className="v2-memctx-sections">
      {parts.map((p) => (
        <div key={p.title} className="v2-memctx-section">
          <div className="v2-memctx-section-title">{p.title}</div>
          <pre className="v2-memctx-section-body">{p.body}</pre>
        </div>
      ))}
    </div>
  );
}

export default function MemoryContext() {
  const [snapshots, setSnapshots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiJson('/api/memory/context?limit=20');
      setSnapshots(d?.snapshots || []);
      setError(null);
    } catch (e) {
      setError(e?.message || 'failed to load snapshots');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 6000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div className="v2-page v2-page--stack v2-memctx" data-testid="v2-marker">
      <Pane
        title="Memory context"
        leading={<BackButton />}
        actions={(
          <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh} aria-label="Refresh">
            <RefreshCw size={13} />
          </button>
        )}
      >
        <p className="v2-p v2-p--muted">
          Every row is one LLM turn. Shows exactly what the multi-memory stack
          assembled for that turn — working memory, known facts from the
          knowledge graph, past episodes (search or recent), and recent
          actions. If a tier is missing from a snapshot, the builder didn't
          find anything worth surfacing for that query.
        </p>
        {error && <div className="v2-chip v2-chip--error">{error}</div>}
      </Pane>

      {loading && snapshots.length === 0 && (
        <Pane title="Loading…"><EmptyState title="Fetching snapshots" /></Pane>
      )}
      {!loading && snapshots.length === 0 && !error && (
        <Pane title="No turns yet">
          <EmptyState
            title="Send a message to see multi-memory in action"
            hint="Every chat / voice / channel turn records what memory fired. Nothing recorded yet."
          />
        </Pane>
      )}

      {snapshots.map((snap, idx) => (
        <Glass key={`${snap.ts}-${idx}`} level={1} radius="md" padding="md" className="v2-memctx-card">
          <header className="v2-memctx-head">
            <div className="v2-memctx-head-left">
              <span className="v2-chip v2-chip--muted">
                <Brain size={11} aria-hidden="true" />
                session {(snap.session_id || '').slice(0, 8) || '—'}
              </span>
              {snap.memory_filter && (
                <span className="v2-chip v2-chip--warn" title="Specialist memory filter">
                  <Tag size={11} aria-hidden="true" /> {snap.memory_filter}
                </span>
              )}
              <span className="v2-chip v2-chip--muted" title={new Date((snap.ts || 0) * 1000).toLocaleString()}>
                <Clock size={11} aria-hidden="true" /> {relativeTime(snap.ts)}
              </span>
              <span className="v2-chip v2-chip--muted" title="Assembly latency">
                {snap.latency_ms ?? 0}ms
              </span>
            </div>
          </header>
          {snap.query && (
            <div className="v2-memctx-query">
              <span className="v2-memctx-query-label">Query</span>
              <code className="v2-memctx-query-body">{snap.query}</code>
            </div>
          )}
          <MemoryBlock content={snap.memory_context || ''} />
        </Glass>
      ))}
    </div>
  );
}
