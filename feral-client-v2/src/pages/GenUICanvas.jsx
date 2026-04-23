/**
 * GenUI Canvas — a live inspector / debug surface for the GenUI runtime.
 *
 * This is not where publishers onboard. Publisher onboarding lives at
 * /apps/publish, which is a real step-by-step flow (scaffold → validate →
 * install → publish). Canvas is about observing and debugging what the
 * agent is rendering right now:
 *
 *   • Live renders   — every sdui / sdui_render / sdui_patch WS frame
 *   • Installed apps — manifest + surface list + regenerate controls
 *   • Themes         — GenUI theme swap for third-party renders
 *   • Components     — the SDUI component vocabulary every spec composes
 *
 * No two-field publisher modal hiding behind a gear icon — if you want
 * to publish, hit the top-right "Publish an app" button.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Trash2, Palette, RefreshCw, Rocket, Boxes } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Tabs from '../ui/Tabs';
import EmptyState from '../ui/EmptyState';
import SduiRenderer, { applySduiPatches } from '../ui/SduiRenderer';
import { useFeralSocket, sendUiEvent } from '../hooks/useFeralSocket';
import { apiJson, apiFetch } from '../lib/api';

export default function GenUICanvas() {
  const [tab, setTab] = useState('live');
  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="GenUI Canvas"
        actions={(
          <>
            <Link to="/apps/publish" className="v2-btn v2-btn--primary">
              <Rocket size={13} /> Publish an app
            </Link>
            <Tabs
              value={tab}
              onChange={setTab}
              items={[
                { id: 'live', label: 'Live' },
                { id: 'apps', label: 'Installed' },
                { id: 'themes', label: 'Themes' },
                { id: 'components', label: 'Components' },
              ]}
            />
          </>
        )}
      >
        <p className="v2-p v2-p--muted">
          A developer inspector for everything FERAL is rendering right now.
          Every frame here is a real SDUI tree — from a skill, a third-party app,
          or a proactive alert. Use <Link to="/apps/publish">/apps/publish</Link>{' '}
          to author your own.
        </p>
      </Pane>
      {tab === 'live' && <LiveTab />}
      {tab === 'apps' && <InstalledAppsTab />}
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
      if (msg?.type === 'sdui_patch') {
        const p = msg.payload || {};
        const targetId = p.screen_id;
        if (!targetId) return;
        setPanes((prev) => prev.map((pane) => (
          pane.id === targetId
            ? { ...pane, tree: applySduiPatches(pane.tree, p.patches || []) }
            : pane
        )));
        return;
      }
      if (msg?.type !== 'sdui_render' && msg?.type !== 'genui_render' && msg?.type !== 'sdui') return;
      const payload = msg.payload || msg;
      const id = payload.screen_id || payload.pane_id || payload.id || `pane_${Date.now()}`;
      const tree = payload.root || payload.tree || payload;
      const title = payload.title || payload.app_id || id;
      setPanes((prev) => {
        const existing = prev.find((p) => p.id === id);
        if (existing) return prev.map((p) => (p.id === id ? { ...p, tree, title } : p));
        return [...prev, { id, tree, title }];
      });
    });
    return unsub;
  }, [socket]);

  const dismiss = (id) => setPanes((prev) => prev.filter((p) => p.id !== id));

  return (
    <Pane title={`Live panes · ${panes.length}`}>
      {panes.length === 0 && (
        <EmptyState
          title="Waiting for a render"
          hint="Any skill, third-party app, or proactive alert that emits an sdui frame appears here in real time."
        />
      )}
      <div className="v2-canvas-grid">
        {panes.map(({ id, tree, title }) => (
          <Glass key={id} level={2} radius="md" padding="md" className="v2-canvas-pane">
            <header className="v2-canvas-head">
              <h3 className="v2-canvas-title">{title}</h3>
              <button type="button" className="v2-btn v2-btn--ghost" onClick={() => dismiss(id)} aria-label="Dismiss pane">
                <Trash2 size={13} />
              </button>
            </header>
            <SduiRenderer
              tree={tree}
              onAction={(action_id, value) => sendUiEvent(socket, {
                screen_id: id,
                action_id,
                value,
              })}
            />
          </Glass>
        ))}
      </div>
    </Pane>
  );
}

function InstalledAppsTab() {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiJson('/api/apps');
      setApps(d?.apps || []);
      setError(null);
    } catch (e) {
      setError(e?.message || 'failed to load apps');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const regenerate = async (app_id, surface_id) => {
    setBusyId(`${app_id}:${surface_id}`);
    try {
      await apiFetch(`/api/apps/${encodeURIComponent(app_id)}/surfaces/${encodeURIComponent(surface_id)}/render`, {
        method: 'POST',
        body: JSON.stringify({ regenerate: true }),
      });
    } finally { setBusyId(null); }
  };

  return (
    <Pane
      title={`Installed apps · ${apps.length}`}
      actions={(
        <>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh} aria-label="Refresh">
            <RefreshCw size={13} />
          </button>
          <Link to="/apps" className="v2-btn v2-btn--ghost">Open launcher</Link>
        </>
      )}
    >
      <p className="v2-p v2-p--muted">
        Every third-party GenUI app installed on this brain — with its manifest,
        declared surfaces, and a regenerate button per hybrid/generated surface
        that clears that surface's cache so the agent re-authors it on next open.
      </p>
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
      {loading && <EmptyState title="Loading…" />}
      {!loading && apps.length === 0 && (
        <EmptyState
          title="No apps installed"
          hint="Publish one from /apps/publish or install from a path / git URL / registry id."
          action={<Link to="/apps/publish" className="v2-btn v2-btn--primary"><Rocket size={13} /> Publish an app</Link>}
        />
      )}
      <div className="v2-canvas-apps">
        {apps.map((app) => (
          <Glass key={app.app_id} level={1} radius="md" padding="md">
            <header className="v2-canvas-head">
              <div>
                <h3 className="v2-canvas-title"><Boxes size={13} /> {app.brand?.name || app.app_id}</h3>
                <div className="v2-p v2-p--muted v2-p--tiny">
                  <code>{app.app_id}</code> · v{app.version} · {app.author || 'unknown author'}
                </div>
              </div>
              <Link to={`/apps/${encodeURIComponent(app.app_id)}`} className="v2-btn v2-btn--ghost">Open</Link>
            </header>
            {app.description && (
              <p className="v2-p v2-p--muted" style={{ marginTop: 6 }}>{app.description}</p>
            )}
            <div className="v2-canvas-surfaces">
              {(app.surfaces || []).map((surface_id) => (
                <div key={surface_id} className="v2-canvas-surface">
                  <code>{surface_id}</code>
                  <button
                    type="button"
                    className="v2-btn v2-btn--ghost"
                    onClick={() => regenerate(app.app_id, surface_id)}
                    disabled={busyId === `${app.app_id}:${surface_id}`}
                    title="Force the agent to regenerate this surface for the current user"
                  >
                    <RefreshCw size={12} /> Regenerate
                  </button>
                </div>
              ))}
            </div>
          </Glass>
        ))}
      </div>
    </Pane>
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
    <Pane title={`Themes · ${themes.length}`} actions={<button type="button" className="v2-btn v2-btn--ghost" onClick={refresh}><RefreshCw size={13} /></button>}>
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
    <Pane title={`Components · ${components.length}`}>
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
