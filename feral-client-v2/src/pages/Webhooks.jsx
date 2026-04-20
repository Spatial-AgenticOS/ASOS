import React, { useCallback, useEffect, useState } from 'react';
import { Copy, Plus, Trash2, RefreshCw } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Modal from '../ui/Modal';
import EmptyState from '../ui/EmptyState';
import { apiJson, apiFetch } from '../lib/api';
import { API_BASE } from '../lib/config';

export default function Webhooks() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/webhooks');
      setItems(d.webhooks || d.items || d || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const remove = async (id) => {
    if (!window.confirm(`Delete webhook ${id}?`)) return;
    await apiFetch(`/api/webhooks/${encodeURIComponent(id)}`, { method: 'DELETE' });
    refresh();
  };

  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="Webhooks"
        actions={(
          <>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh}><RefreshCw size={13} /></button>
            <button type="button" className="v2-btn v2-btn--primary" onClick={() => setShowNew(true)}><Plus size={13} /> New webhook</button>
          </>
        )}
      >
        <p className="v2-p v2-p--muted">
          External services POST to these URLs to trigger FERAL. Each webhook has a secret; verify the X-FERAL-Signature header.
        </p>
        {loading && <EmptyState title="Loading…" />}
        {!loading && items.length === 0 && <EmptyState title="No webhooks yet" />}
        <ul className="v2-mem-list">
          {items.map((w) => {
            const id = w.id || w.webhook_id;
            const url = `${API_BASE}/api/webhooks/${encodeURIComponent(w.app_id || id)}`;
            return (
              <li key={id}>
                <Glass level={0} radius="md" padding="md">
                  <div className="v2-flow-card-head">
                    <div className="v2-flow-card-title">{w.name || w.app_id || id}</div>
                    <button type="button" className="v2-btn v2-btn--ghost" onClick={() => navigator.clipboard.writeText(url)} title="Copy URL"><Copy size={12} /></button>
                    <button type="button" className="v2-btn v2-btn--ghost" onClick={() => remove(id)}><Trash2 size={12} /></button>
                  </div>
                  <code className="v2-code-inline" style={{ display: 'block', marginTop: 6 }}>{url}</code>
                </Glass>
              </li>
            );
          })}
        </ul>
      </Pane>

      {showNew && <NewWebhookModal onClose={() => setShowNew(false)} onCreated={() => { setShowNew(false); refresh(); }} />}
    </div>
  );
}

function NewWebhookModal({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [appId, setAppId] = useState('');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(null);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await apiFetch('/api/webhooks/create', {
        method: 'POST',
        body: JSON.stringify({ name, app_id: appId || name.toLowerCase().replace(/\s+/g, '_') }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) setError(body?.error || `${r.status}`);
      else setCreated(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const close = () => { onCreated?.(); onClose(); };

  return (
    <Modal
      open
      onClose={created ? close : onClose}
      title={created ? 'Webhook created' : 'New webhook'}
      actions={created ? (
        <button type="button" className="v2-btn v2-btn--primary" onClick={close}>Done</button>
      ) : (
        <>
          <button type="button" className="v2-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="v2-btn v2-btn--primary" onClick={submit} disabled={busy || !name}>
            {busy ? 'Creating…' : 'Create'}
          </button>
        </>
      )}
    >
      {!created && (
        <div className="v2-setting-stack">
          <label className="v2-setting-row"><div className="v2-setting-label"><div>Name</div></div>
            <div className="v2-setting-control"><input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="zapier-weather" /></div>
          </label>
          <label className="v2-setting-row"><div className="v2-setting-label"><div>App ID (optional)</div></div>
            <div className="v2-setting-control"><input className="v2-input" value={appId} onChange={(e) => setAppId(e.target.value)} placeholder="auto from name" /></div>
          </label>
        </div>
      )}
      {created && (
        <div>
          <div className="v2-chip v2-chip--live" style={{ marginBottom: 8 }}>Created ✓</div>
          <pre className="v2-code">{JSON.stringify(created, null, 2)}</pre>
          <p className="v2-p v2-p--muted">Copy the URL and secret — you won't see the secret again.</p>
        </div>
      )}
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </Modal>
  );
}
