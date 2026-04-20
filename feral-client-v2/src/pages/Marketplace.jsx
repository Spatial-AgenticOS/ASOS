import React, { useCallback, useEffect, useState } from 'react';
import { Search, Download, Trash2, RefreshCw } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Tabs from '../ui/Tabs';
import EmptyState from '../ui/EmptyState';
import { apiJson, apiFetch } from '../lib/api';

const KINDS = ['skill', 'daemon', 'mcp', 'channel', 'provider', 'memory', 'workflow', 'agent'];

export default function Marketplace() {
  const [tab, setTab] = useState('browse');
  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="Marketplace"
        actions={(
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { id: 'browse', label: 'Browse' },
              { id: 'installed', label: 'Installed' },
            ]}
          />
        )}
      >
        <p className="v2-p v2-p--muted">
          Signed community registry at registry.feral.sh. Install any item, uninstall, or update in-place.
        </p>
      </Pane>
      {tab === 'browse' && <BrowseTab />}
      {tab === 'installed' && <InstalledTab />}
    </div>
  );
}

function BrowseTab() {
  const [kind, setKind] = useState('skill');
  const [query, setQuery] = useState('');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const url = query.trim()
        ? `/api/marketplace/search?q=${encodeURIComponent(query)}&kind=${kind}`
        : `/api/marketplace/catalog?kind=${kind}`;
      const d = await apiJson(url);
      setItems(d.items || d.results || d || []);
    } catch { setItems([]); }
    finally { setLoading(false); }
  }, [kind, query]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const install = async (it) => {
    const id = it.id || it.item_id;
    setBusy(id);
    try {
      const r = await apiFetch('/api/marketplace/install', {
        method: 'POST',
        body: JSON.stringify({ id, kind: it.kind || kind }),
      });
      const body = await r.json().catch(() => ({}));
      setMsg(r.ok ? `Installed ${it.name || id}` : (body?.error || `${r.status}`));
      setTimeout(() => setMsg(null), 4000);
    } finally { setBusy(null); }
  };

  return (
    <Pane
      title="Browse catalog"
      actions={(
        <>
          <input
            type="search"
            className="v2-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            style={{ minWidth: 160 }}
          />
          <Tabs value={kind} onChange={setKind} items={KINDS.map((k) => ({ id: k, label: k }))} />
          <button type="button" className="v2-btn v2-btn--ghost" onClick={fetchList}><RefreshCw size={13} /></button>
        </>
      )}
    >
      {msg && <div className="v2-chip v2-chip--live">{msg}</div>}
      {loading && <EmptyState title="Loading…" />}
      {!loading && items.length === 0 && <EmptyState title={`Nothing in ${kind} yet`} />}
      <div className="v2-skills-grid">
        {items.map((it) => (
          <Glass key={it.id || it.name} level={0} radius="md" padding="md" className="v2-skill-card">
            <header className="v2-skill-card-head">
              <h3 className="v2-skill-card-name">
                {it.name || it.skill_id || it.id}
                {it.verified && <span className="v2-chip v2-chip--live" style={{ marginLeft: 6 }}>verified</span>}
              </h3>
              <code className="v2-skill-card-id">v{it.version || '0.0.0'}</code>
            </header>
            <p className="v2-p v2-p--muted">{it.description || '—'}</p>
            <div className="v2-skill-card-meta">
              {it.publisher && <span className="v2-chip v2-chip--muted">by {it.publisher}</span>}
              {it.downloads != null && <span className="v2-chip">{it.downloads} installs</span>}
            </div>
            <div className="v2-forge-actions">
              <button type="button" className="v2-btn v2-btn--primary" onClick={() => install(it)} disabled={busy === (it.id || it.item_id)}>
                <Download size={12} /> {busy === (it.id || it.item_id) ? 'Installing…' : 'Install'}
              </button>
            </div>
          </Glass>
        ))}
      </div>
    </Pane>
  );
}

function InstalledTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/marketplace/installed');
      setItems(d.installed || d.items || d || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const uninstall = async (id) => {
    if (!window.confirm(`Uninstall ${id}?`)) return;
    setBusy(id);
    try {
      await apiFetch(`/api/marketplace/uninstall/${encodeURIComponent(id)}`, { method: 'DELETE' });
      refresh();
    } finally { setBusy(null); }
  };

  const update = async (id) => {
    setBusy(id);
    try {
      await apiFetch(`/api/marketplace/update/${encodeURIComponent(id)}`, { method: 'POST' });
      refresh();
    } finally { setBusy(null); }
  };

  return (
    <Pane title={`Installed (${items.length})`} actions={<button type="button" className="v2-btn v2-btn--ghost" onClick={refresh}><RefreshCw size={13} /></button>}>
      {loading && <EmptyState title="Loading…" />}
      {!loading && items.length === 0 && <EmptyState title="Nothing installed yet" hint="Browse the catalog and install anything." />}
      <ul className="v2-mem-list">
        {items.map((it) => {
          const id = it.skill_id || it.id;
          return (
            <li key={id}>
              <Glass level={0} radius="md" padding="md">
                <div className="v2-flow-card-head">
                  <div className="v2-flow-card-title">{it.name || id}</div>
                  <div className="v2-flow-card-status">{it.kind} · v{it.version}</div>
                </div>
                <div className="v2-forge-actions">
                  <button type="button" className="v2-btn" onClick={() => update(id)} disabled={busy === id}>Update</button>
                  <button type="button" className="v2-btn" onClick={() => uninstall(id)} disabled={busy === id}><Trash2 size={12} /> Uninstall</button>
                </div>
              </Glass>
            </li>
          );
        })}
      </ul>
    </Pane>
  );
}
