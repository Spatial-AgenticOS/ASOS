/**
 * AppSurface — renders the active surface of a third-party GenUI app.
 *
 * Flow:
 *   1. On mount, GET /api/apps/<app_id>/manifest to build the surface
 *      navigation rail, then POST /api/apps/<app_id>/open to get the
 *      entry surface tree.
 *   2. Tree mounts via <SduiRenderer>. Every action fires
 *      sendUiEvent(socket, { screen_id, action_id, value, app_id }) so
 *      the brain's ui_handlers path validates the action against the
 *      publisher's action_contract before the orchestrator touches it.
 *   3. The shared FeralSocket also listens for `sdui_patch` messages
 *      scoped to this surface's `screen_id` and mutates the tree in
 *      place via applySduiPatches.
 *   4. sdui messages for this app (e.g. from navigate-handler
 *      dispatches) swap the active surface without a full reload.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import EmptyState from '../ui/EmptyState';
import SduiRenderer, { applySduiPatches } from '../ui/SduiRenderer';
import { useFeralSocket, sendUiEvent } from '../hooks/useFeralSocket';
import { apiJson, apiFetch } from '../lib/api';

export default function AppSurface() {
  const { app_id: appId } = useParams();
  const socket = useFeralSocket();
  const [manifest, setManifest] = useState(null);
  const [activeSurface, setActiveSurface] = useState(null);
  const [screenId, setScreenId] = useState(null);
  const [tree, setTree] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const openSurface = useCallback(async (surface_id, { regenerate = false, data = {} } = {}) => {
    if (!appId) return;
    setLoading(true);
    try {
      const r = await apiFetch(`/api/apps/${encodeURIComponent(appId)}/open`, {
        method: 'POST',
        body: JSON.stringify({
          surface_id,
          data,
          regenerate,
          user_fingerprint: 'v2-user',
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(body?.detail || body?.error || `${r.status}`);
        return;
      }
      setActiveSurface(body.surface_id || surface_id);
      setScreenId(body.screen_id);
      setTree(body.root);
      setError(null);
    } catch (e) {
      setError(e?.message || 'failed to open surface');
    } finally {
      setLoading(false);
    }
  }, [appId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!appId) return;
      try {
        const data = await apiJson(`/api/apps/${encodeURIComponent(appId)}/manifest`);
        if (cancelled) return;
        setManifest(data?.manifest || null);
        const entry = data?.manifest?.entry_surface_id;
        if (entry) await openSurface(entry);
      } catch (e) {
        if (!cancelled) setError(e?.message || 'failed to fetch manifest');
      }
    })();
    return () => { cancelled = true; };
  }, [appId, openSurface]);

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      if (!msg || typeof msg !== 'object') return;
      if (msg.type === 'sdui_patch') {
        const p = msg.payload || {};
        if (p.screen_id && screenId && p.screen_id === screenId) {
          setTree((prev) => applySduiPatches(prev, p.patches || []));
        }
        return;
      }
      if (msg.type !== 'sdui') return;
      const p = msg.payload || {};
      // Only intercept messages scoped to this app's surface id space.
      if (typeof p.screen_id !== 'string') return;
      if (!p.screen_id.startsWith(`${appId}:`)) return;
      const parts = p.screen_id.split(':');
      const surfaceFromId = parts[1];
      setActiveSurface(surfaceFromId);
      setScreenId(p.screen_id);
      setTree(p.root || null);
    });
    return unsub;
  }, [socket, appId, screenId]);

  const onAction = useCallback((action_id, value) => {
    sendUiEvent(socket, {
      screen_id: screenId || `${appId}:${activeSurface || 'home'}:v2-user`,
      action_id,
      value,
      app_id: appId,
    });
  }, [socket, screenId, appId, activeSurface]);

  const surfaces = useMemo(() => {
    if (!manifest?.surfaces) return [];
    return manifest.surfaces;
  }, [manifest]);

  const brand = manifest?.brand || {};

  return (
    <div className="v2-page v2-page--split" data-testid="v2-marker">
      <aside className="v2-settings-nav">
        <Glass level={1} radius="lg" padding="sm">
          <div style={{ marginBottom: 10 }}>
            <Link to="/apps" className="v2-btn v2-btn--ghost">
              <ChevronLeft size={12} /> Apps
            </Link>
          </div>
          {brand.name ? (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontWeight: 700 }}>{brand.name}</div>
              <div className="v2-p v2-p--muted v2-p--tiny">{appId}</div>
            </div>
          ) : null}
          <ul className="v2-settings-list" data-testid="v2-appsurface-nav">
            {surfaces.map((s) => {
              const id = s.surface_id || s;
              const title = s.title || id;
              const isActive = id === activeSurface;
              return (
                <li key={id}>
                  <button
                    type="button"
                    className={`v2-settings-btn${isActive ? ' is-active' : ''}`}
                    onClick={() => openSurface(id)}
                    data-testid={`v2-appsurface-tab-${id}`}
                  >
                    {title}
                  </button>
                </li>
              );
            })}
          </ul>
        </Glass>
      </aside>

      <Pane
        title={activeSurface || appId}
        actions={(
          <button
            type="button"
            className="v2-btn v2-btn--ghost"
            onClick={() => activeSurface && openSurface(activeSurface, { regenerate: true })}
            aria-label="Regenerate this surface"
            title="Force the agent to regenerate this surface (clears the cached render)"
          >
            <RefreshCw size={13} />
          </button>
        )}
      >
        {error && <div className="v2-chip v2-chip--error">{error}</div>}
        {loading && !tree && <EmptyState title="Rendering…" hint="The brain is hydrating the surface." />}
        {!loading && !tree && !error && (
          <EmptyState title="No surface loaded" hint="Pick a surface from the left rail." />
        )}
        {tree && (
          <SduiRenderer tree={tree} onAction={onAction} />
        )}
      </Pane>
    </div>
  );
}
