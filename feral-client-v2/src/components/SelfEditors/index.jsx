/**
 * SelfEditors — reusable IDENTITY / SOUL / MEMORY.md / ABOUT-ME editors.
 *
 * Originally lived inline in feral-client-v2/src/pages/Identity.jsx.
 * Factored out so both the standalone /identity route AND the new
 * Settings -> Self section can import the exact same editors without
 * duplicated state/fetch logic.
 *
 * Brain routes touched:
 *   GET/POST /api/identity
 *   GET/POST /api/identity/soul
 *   GET      /api/identity/memory_md
 *   GET/POST /api/about-me
 *   POST     /api/about-me/{id}/confirm
 *   POST     /api/about-me/{id}/reject
 *   DELETE   /api/about-me/{id}
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Save, Plus, CheckCircle2, XCircle, Trash2 } from 'lucide-react';
import Pane from '../../ui/Pane';
import Tabs from '../../ui/Tabs';
import EmptyState from '../../ui/EmptyState';
import CodeEditor from '../../ui/CodeEditor';
import Glass from '../../ui/Glass';
import { apiJson, apiFetch } from '../../lib/api';


export function IdentityEditor() {
  const [data, setData] = useState(null);
  const [text, setText] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/identity');
      setData(d);
      setText(JSON.stringify(d, null, 2));
      setDirty(false);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch (err) {
        setError('Invalid JSON — fix the syntax before saving.');
        return;
      }
      const r = await apiFetch('/api/identity', {
        method: 'POST',
        body: JSON.stringify(parsed),
      });
      if (!r.ok) {
        setError(`${r.status} ${await r.text()}`);
        return;
      }
      setSaved(true);
      setDirty(false);
      setTimeout(() => setSaved(false), 2000);
      refresh();
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <Pane title="IDENTITY"><EmptyState title="Loading…" /></Pane>;

  return (
    <Pane title="IDENTITY (editable)" actions={(
      <>
        {dirty && <span className="v2-chip v2-chip--warn">unsaved</span>}
        {saved && <span className="v2-chip v2-chip--live">saved</span>}
        <button type="button" className="v2-btn v2-btn--primary" onClick={save} disabled={!dirty || busy}>
          <Save size={13} /> Save
        </button>
      </>
    )}>
      <CodeEditor
        value={text}
        onChange={(v) => { setText(v); setDirty(true); }}
        language="json"
        rows={24}
        aria-label="IDENTITY editor"
      />
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </Pane>
  );
}


export function SoulEditor() {
  const [text, setText] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiJson('/api/identity/soul').then((d) => {
      setText(d?.soul ?? d?.content ?? d ?? '');
    }).catch((e) => setError(e.message));
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const r = await apiFetch('/api/identity/soul', {
        method: 'POST',
        body: JSON.stringify({ soul: text, content: text }),
      });
      if (!r.ok) setError(`${r.status}`);
      else { setSaved(true); setDirty(false); setTimeout(() => setSaved(false), 2000); }
    } finally { setBusy(false); }
  };

  return (
    <Pane title="SOUL.md" actions={(
      <>
        {dirty && <span className="v2-chip v2-chip--warn">unsaved</span>}
        {saved && <span className="v2-chip v2-chip--live">saved</span>}
        <button type="button" className="v2-btn v2-btn--primary" onClick={save} disabled={!dirty || busy}>
          <Save size={13} /> Save
        </button>
      </>
    )}>
      <CodeEditor
        value={text}
        onChange={(v) => { setText(v); setDirty(true); }}
        language="markdown"
        rows={24}
        aria-label="SOUL editor"
      />
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </Pane>
  );
}


export function MemoryMdViewer() {
  const [text, setText] = useState('');
  const [error, setError] = useState(null);

  useEffect(() => {
    apiJson('/api/identity/memory_md').then((d) => {
      setText(d?.memory_md || d?.content || d || '');
    }).catch((e) => setError(e.message));
  }, []);

  return (
    <Pane title="MEMORY.md (read-only)">
      <p className="v2-p v2-p--muted">Auto-compiled summary of what the Brain has learned about you. Edit SOUL / IDENTITY instead.</p>
      <CodeEditor value={text} readOnly rows={22} language="markdown" />
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </Pane>
  );
}


const ABOUT_ME_KINDS = [
  'preference', 'relationship', 'place', 'routine',
  'context', 'goal', 'taboo',
];

export function AboutMeEditor() {
  const [facts, setFacts] = useState([]);
  const [error, setError] = useState(null);
  const [busyIds, setBusyIds] = useState(() => new Set());
  const [filter, setFilter] = useState('all');
  const [draft, setDraft] = useState({ kind: 'preference', text: '', tags: '' });

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/about-me');
      setFacts(d?.facts || []);
      setError(null);
    } catch (e) {
      setError(e?.message || 'failed to load about-me');
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const withBusy = useCallback(async (id, fn) => {
    const next = new Set(busyIds); next.add(id); setBusyIds(next);
    try { await fn(); } finally {
      const done = new Set(busyIds); done.delete(id); setBusyIds(done);
    }
  }, [busyIds]);

  const confirm = useCallback((f) => withBusy(f.id, async () => {
    await apiFetch(`/api/about-me/${encodeURIComponent(f.id)}/confirm`, { method: 'POST' });
    refresh();
  }), [refresh, withBusy]);

  const reject = useCallback((f) => withBusy(f.id, async () => {
    await apiFetch(`/api/about-me/${encodeURIComponent(f.id)}/reject`, { method: 'POST' });
    refresh();
  }), [refresh, withBusy]);

  const remove = useCallback((f) => withBusy(f.id, async () => {
    await apiFetch(`/api/about-me/${encodeURIComponent(f.id)}`, { method: 'DELETE' });
    refresh();
  }), [refresh, withBusy]);

  const add = useCallback(async (e) => {
    e.preventDefault();
    if (!draft.text.trim()) return;
    const r = await apiFetch('/api/about-me', {
      method: 'POST',
      body: JSON.stringify({
        kind: draft.kind,
        text: draft.text.trim(),
        tags: draft.tags.split(',').map((s) => s.trim()).filter(Boolean),
      }),
    });
    if (r.ok) {
      setDraft({ kind: draft.kind, text: '', tags: '' });
      refresh();
    } else {
      setError(`${r.status} ${await r.text()}`);
    }
  }, [draft, refresh]);

  const filtered = useMemo(() => {
    if (filter === 'all') return facts;
    if (filter === 'inferred') return facts.filter((f) => f.source !== 'user_stated');
    return facts.filter((f) => f.kind === filter);
  }, [facts, filter]);

  return (
    <Pane
      title="About Me"
      actions={(
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="v2-btn v2-btn--ghost"
          aria-label="Filter about-me facts"
          data-testid="aboutme-filter"
        >
          <option value="all">All</option>
          <option value="inferred">Inferred (unconfirmed)</option>
          {ABOUT_ME_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      )}
    >
      <p className="v2-p v2-p--muted">
        Everything the Brain knows about you — one row per fact. Inferred rows from chat
        need your confirmation; taboos tell me never to bring that topic up in suggestions.
      </p>
      {error && <div className="v2-chip v2-chip--error">{error}</div>}

      <form onSubmit={add} className="v2-foryou-addrow" style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <select
          value={draft.kind}
          onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
          className="v2-btn v2-btn--ghost"
          aria-label="New about-me kind"
          data-testid="aboutme-new-kind"
        >
          {ABOUT_ME_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <input
          type="text"
          placeholder="e.g. I don't drink coffee after 4pm"
          value={draft.text}
          onChange={(e) => setDraft({ ...draft, text: e.target.value })}
          className="v2-input"
          style={{ flex: 1 }}
          data-testid="aboutme-new-text"
        />
        <input
          type="text"
          placeholder="tags (comma separated)"
          value={draft.tags}
          onChange={(e) => setDraft({ ...draft, tags: e.target.value })}
          className="v2-input"
          style={{ width: 160 }}
        />
        <button type="submit" className="v2-btn v2-btn--primary" disabled={!draft.text.trim()}>
          <Plus size={12} /> Add
        </button>
      </form>

      {filtered.length === 0 ? (
        <EmptyState
          title="Nothing here yet"
          hint="Tell me something about yourself in chat, or click Add above."
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {filtered.map((f) => {
            const busy = busyIds.has(f.id);
            const inferred = f.source !== 'user_stated' && f.confidence < 1.0;
            return (
              <Glass key={f.id} level={0} radius="md" padding="sm">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span className="v2-chip v2-chip--muted" style={{ textTransform: 'capitalize' }}>{f.kind}</span>
                  {inferred && <span className="v2-chip v2-chip--warn">inferred · {Math.round(f.confidence * 100)}%</span>}
                  {!inferred && <span className="v2-chip v2-chip--live">confirmed</span>}
                  <span className="v2-p v2-p--muted v2-p--tiny">source: {f.source.replace(/_/g, ' ')}</span>
                  <div style={{ flex: 1, minWidth: 0, fontWeight: 500 }}>{f.text}</div>
                  {inferred && (
                    <button type="button" className="v2-btn v2-btn--primary" disabled={busy} onClick={() => confirm(f)} data-testid={`aboutme-confirm-${f.id}`}>
                      <CheckCircle2 size={12} /> Confirm
                    </button>
                  )}
                  {inferred && (
                    <button type="button" className="v2-btn" disabled={busy} onClick={() => reject(f)} data-testid={`aboutme-reject-${f.id}`}>
                      <XCircle size={12} /> Reject
                    </button>
                  )}
                  <button type="button" className="v2-btn v2-btn--ghost" disabled={busy} onClick={() => remove(f)} aria-label="Delete fact" data-testid={`aboutme-delete-${f.id}`}>
                    <Trash2 size={12} />
                  </button>
                </div>
                {Array.isArray(f.tags) && f.tags.length > 0 && (
                  <div className="v2-p v2-p--muted v2-p--tiny" style={{ marginTop: 4 }}>
                    tags: {f.tags.join(', ')}
                  </div>
                )}
              </Glass>
            );
          })}
        </div>
      )}
    </Pane>
  );
}


/**
 * SelfWorkspace — a Tabs strip wrapping all four editors. Reused by
 * the /identity route AND the Settings -> Self section so users find
 * the same editors wherever they look first.
 */
export function SelfWorkspace({ defaultTab = 'identity', showIntro = true }) {
  const [tab, setTab] = useState(defaultTab);

  return (
    <div>
      <Pane
        title="Self — IDENTITY / SOUL / MEMORY / ABOUT-ME"
        actions={(
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { id: 'identity', label: 'IDENTITY' },
              { id: 'soul', label: 'SOUL' },
              { id: 'memory', label: 'MEMORY' },
              { id: 'aboutme', label: 'ABOUT ME' },
            ]}
          />
        )}
      >
        {showIntro && (
          <p className="v2-p v2-p--muted">
            These layers shape FERAL's persona and its model of you. IDENTITY.yaml holds the agent's
            name + rules; SOUL.md is free-form voice; MEMORY.md auto-compiles past interactions;
            ABOUT ME is a structured, queryable self-model you can confirm fact-by-fact.
          </p>
        )}
      </Pane>

      {tab === 'identity' && <IdentityEditor />}
      {tab === 'soul' && <SoulEditor />}
      {tab === 'memory' && <MemoryMdViewer />}
      {tab === 'aboutme' && <AboutMeEditor />}
    </div>
  );
}
