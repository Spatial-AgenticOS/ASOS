/**
 * SelfEditors — reusable IDENTITY / SOUL / MEMORY.md editors.
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
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import Pane from '../../ui/Pane';
import Tabs from '../../ui/Tabs';
import EmptyState from '../../ui/EmptyState';
import CodeEditor from '../../ui/CodeEditor';
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


/**
 * SelfWorkspace — a Tabs strip wrapping all three editors. Reused by
 * the /identity route AND the Settings -> Self section so users find
 * the same editors wherever they look first.
 */
export function SelfWorkspace({ defaultTab = 'identity', showIntro = true }) {
  const [tab, setTab] = useState(defaultTab);

  return (
    <div>
      <Pane
        title="Self — IDENTITY / SOUL / MEMORY"
        actions={(
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { id: 'identity', label: 'IDENTITY' },
              { id: 'soul', label: 'SOUL' },
              { id: 'memory', label: 'MEMORY' },
            ]}
          />
        )}
      >
        {showIntro && (
          <p className="v2-p v2-p--muted">
            These files shape FERAL's persona at runtime. IDENTITY.yaml holds structured facts
            about you; SOUL.md is free-form voice / values; MEMORY.md auto-compiles what the Brain
            learned about you from past interactions.
          </p>
        )}
      </Pane>

      {tab === 'identity' && <IdentityEditor />}
      {tab === 'soul' && <SoulEditor />}
      {tab === 'memory' && <MemoryMdViewer />}
    </div>
  );
}
