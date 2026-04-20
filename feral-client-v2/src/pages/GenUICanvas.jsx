import React, { useCallback, useEffect, useState } from 'react';
import { Plus, Trash2, Palette, RefreshCw, Eye } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Modal from '../ui/Modal';
import Tabs from '../ui/Tabs';
import EmptyState from '../ui/EmptyState';
import { useFeralSocket } from '../hooks/useFeralSocket';
import { apiJson, apiFetch } from '../lib/api';

export default function GenUICanvas() {
  const [tab, setTab] = useState('live');
  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="GenUI Canvas"
        actions={(
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { id: 'live', label: 'Live renders' },
              { id: 'providers', label: 'Providers' },
              { id: 'themes', label: 'Themes' },
              { id: 'components', label: 'Components' },
            ]}
          />
        )}
      >
        <p className="v2-p v2-p--muted">
          Third-party apps publish A2UI specs through registered GenUI providers. Live renders appear below; themes control how they look.
        </p>
      </Pane>
      {tab === 'live' && <LiveTab />}
      {tab === 'providers' && <ProvidersTab />}
      {tab === 'themes' && <ThemesTab />}
      {tab === 'components' && <ComponentsTab />}
    </div>
  );
}

function LiveTab() {
  const socket = useFeralSocket();
  const [panes, setPanes] = useState([]);

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      if (msg?.type !== 'sdui_render' && msg?.type !== 'genui_render' && msg?.type !== 'sdui') return;
      const payload = msg.payload || msg;
      const id = payload.pane_id || payload.id || `pane_${Date.now()}`;
      setPanes((prev) => {
        const existing = prev.find((p) => p.id === id);
        if (existing) return prev.map((p) => (p.id === id ? { ...p, spec: payload } : p));
        return [...prev, { id, spec: payload }];
      });
    });
    return unsub;
  }, [socket]);

  const dismiss = (id) => setPanes((prev) => prev.filter((p) => p.id !== id));

  return (
    <Pane title={`Live panes (${panes.length})`}>
      {panes.length === 0 && (
        <EmptyState title="Waiting for a render" hint="Any skill / third-party app that emits sdui_render appears here." />
      )}
      <div className="v2-canvas-grid">
        {panes.map(({ id, spec }) => (
          <Glass key={id} level={2} radius="md" padding="md" className="v2-canvas-pane">
            <header className="v2-canvas-head">
              <h3 className="v2-canvas-title">{spec.title || spec.app_id || id}</h3>
              <button type="button" className="v2-btn v2-btn--ghost" onClick={() => dismiss(id)}>×</button>
            </header>
            <pre className="v2-code">{JSON.stringify(spec, null, 2).slice(0, 1200)}</pre>
          </Glass>
        ))}
      </div>
    </Pane>
  );
}

function ProvidersTab() {
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/genui/providers');
      setProviders(d.providers || d || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <>
      <Pane
        title={`Registered providers (${providers.length})`}
        actions={(
          <>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh}><RefreshCw size={13} /></button>
            <button type="button" className="v2-btn v2-btn--primary" onClick={() => setShowNew(true)}>
              <Plus size={13} /> Register
            </button>
          </>
        )}
      >
        {loading && <EmptyState title="Loading…" />}
        {!loading && providers.length === 0 && <EmptyState title="No GenUI providers registered" />}
        <ul className="v2-mem-list">
          {providers.map((p) => (
            <li key={p.id || p.provider_id}>
              <Glass level={0} radius="md" padding="md">
                <div className="v2-flow-card-head">
                  <div className="v2-flow-card-title">{p.name || p.id}</div>
                  <code className="v2-flow-card-status">{p.id || p.provider_id}</code>
                </div>
                {p.description && <div className="v2-mem-content">{p.description}</div>}
              </Glass>
            </li>
          ))}
        </ul>
      </Pane>
      {showNew && <RegisterProviderModal onClose={() => setShowNew(false)} onRegistered={() => { setShowNew(false); refresh(); }} />}
    </>
  );
}

function RegisterProviderModal({ onClose, onRegistered }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await apiFetch('/api/genui/providers/register', {
        method: 'POST',
        body: JSON.stringify({ id, name, description }),
      });
      if (!r.ok) setError(`${r.status}`);
      else onRegistered();
    } finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title="Register GenUI provider" actions={(
      <>
        <button type="button" className="v2-btn" onClick={onClose}>Cancel</button>
        <button type="button" className="v2-btn v2-btn--primary" onClick={submit} disabled={busy || !id || !name}>
          {busy ? 'Registering…' : 'Register'}
        </button>
      </>
    )}>
      <label className="v2-step-field"><span>Provider id</span><input className="v2-input" value={id} onChange={(e) => setId(e.target.value)} placeholder="my-app" /></label>
      <label className="v2-step-field"><span>Name</span><input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="v2-step-field"><span>Description</span><textarea className="v2-code-editor" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </Modal>
  );
}

function ThemesTab() {
  const [themes, setThemes] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try { const d = await apiJson('/api/genui/themes'); setThemes(d.themes || d || []); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const activate = async (id) => {
    await apiFetch('/api/genui/themes/activate', {
      method: 'POST',
      body: JSON.stringify({ theme_id: id }),
    });
    refresh();
  };

  return (
    <Pane title={`Themes (${themes.length})`} actions={<button type="button" className="v2-btn v2-btn--ghost" onClick={refresh}><RefreshCw size={13} /></button>}>
      {loading && <EmptyState title="Loading…" />}
      {!loading && themes.length === 0 && <EmptyState title="No themes" />}
      <div className="v2-skills-grid">
        {themes.map((t) => (
          <Glass key={t.id} level={0} radius="md" padding="md" className="v2-skill-card">
            <header className="v2-skill-card-head">
              <h3 className="v2-skill-card-name"><Palette size={12} /> {t.name || t.id}</h3>
              {t.active && <span className="v2-chip v2-chip--live">active</span>}
            </header>
            <div className="v2-forge-actions">
              <button type="button" className={`v2-btn ${t.active ? '' : 'v2-btn--primary'}`} onClick={() => activate(t.id)} disabled={t.active}>
                {t.active ? 'In use' : 'Activate'}
              </button>
            </div>
          </Glass>
        ))}
      </div>
    </Pane>
  );
}

function ComponentsTab() {
  const [components, setComponents] = useState([]);
  useEffect(() => { apiJson('/api/genui/components').then((d) => setComponents(d.components || d || [])); }, []);
  return (
    <Pane title={`Components (${components.length})`}>
      <p className="v2-p v2-p--muted">Every renderable SDUI component type. Third-party specs compose these.</p>
      {components.length === 0 && <EmptyState title="No components registered" />}
      <div className="v2-skill-card-phrases">
        {components.map((c, i) => (
          <span key={c.type || c.name || i} className="v2-chip">{c.type || c.name || c}</span>
        ))}
      </div>
    </Pane>
  );
}
