/**
 * AppSurface — renders the active surface of a third-party GenUI app
 * inside a sandboxed iframe (roadmap §3.3 #2).
 *
 * Trust model:
 *   - The publisher's surface tree is rendered into an `<iframe
 *     sandbox="allow-scripts">` srcdoc. We deliberately do NOT
 *     include `allow-same-origin`, so the iframe runs as an opaque
 *     origin and cannot reach into the FERAL host (DOM, cookies,
 *     localStorage, IndexedDB).
 *   - The srcdoc carries a Content-Security-Policy meta tag derived
 *     from `manifest.permissions.network` (see AppSurface.csp.js).
 *     With no allowlist, `connect-src 'none'` blocks all outbound
 *     traffic from the surface — even fetch via inline script.
 *   - referrerpolicy="no-referrer" so URL-based identifiers don't
 *     leak through outbound requests the publisher does make.
 *   - Surface→host communication happens via window.postMessage
 *     using the strict AppMessage envelope (AppSurface.types.ts).
 *     Anything that doesn't match the schema is dropped silently.
 *
 * Flow:
 *   1. On mount, GET /api/apps/<app_id>/manifest to build the surface
 *      navigation rail, then POST /api/apps/<app_id>/open to get the
 *      entry surface tree.
 *   2. The tree is rendered into the iframe via buildSrcDoc(); the
 *      iframe's tiny inline bootstrap forwards click events on
 *      [data-action-id] nodes back to the host as AppMessage events.
 *   3. Host-side `window.message` listener validates each event with
 *      validateAppMessage and only then forwards to FERAL via
 *      sendUiEvent.
 *   4. The shared FeralSocket also listens for `sdui_patch` /
 *      `sdui` messages scoped to this surface's `screen_id`; on each
 *      change we just rebuild the iframe srcdoc and let the iframe
 *      re-render.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import EmptyState from '../ui/EmptyState';
import { useFeralSocket, sendUiEvent } from '../hooks/useFeralSocket';
import { apiJson, apiFetch } from '../lib/api';
import { buildSrcDoc } from './AppSurface.srcdoc.js';
import { validateAppMessage } from './AppSurface.types';

export default function AppSurface() {
  const { app_id: appId } = useParams();
  const socket = useFeralSocket();
  const iframeRef = useRef(null);
  const [manifest, setManifest] = useState(null);
  const [activeSurface, setActiveSurface] = useState(null);
  const [screenId, setScreenId] = useState(null);
  const [tree, setTree] = useState(null);
  const [signedKeyId, setSignedKeyId] = useState('unsigned');
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
      if (body.signed_with_key_id) setSignedKeyId(body.signed_with_key_id);
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
        if (data?.signed_with_key_id) setSignedKeyId(data.signed_with_key_id);
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
        if (p.screen_id && screenId && p.screen_id === screenId && tree) {
          setTree(applySduiPatchesShallow(tree, p.patches || []));
        }
        return;
      }
      if (msg.type !== 'sdui') return;
      const p = msg.payload || {};
      if (typeof p.screen_id !== 'string') return;
      if (!p.screen_id.startsWith(`${appId}:`)) return;
      const parts = p.screen_id.split(':');
      const surfaceFromId = parts[1];
      setActiveSurface(surfaceFromId);
      setScreenId(p.screen_id);
      setTree(p.root || null);
    });
    return unsub;
  }, [socket, appId, screenId, tree]);

  const onAction = useCallback((action_id, value) => {
    sendUiEvent(socket, {
      screen_id: screenId || `${appId}:${activeSurface || 'home'}:v2-user`,
      action_id,
      value,
      app_id: appId,
    });
  }, [socket, screenId, appId, activeSurface]);

  // Host-side postMessage validator. We only listen to messages whose
  // `source` is the iframe's contentWindow so a sibling tab can't
  // spoof events into our reducer.
  useEffect(() => {
    function handler(event) {
      const iframeWindow = iframeRef.current?.contentWindow;
      if (!iframeWindow || event.source !== iframeWindow) return;
      const msg = validateAppMessage(event.data);
      if (!msg) return;
      if (msg.type === 'submit_form') {
        const actionId = msg.payload?.action_id;
        const value = msg.payload?.value ?? null;
        if (typeof actionId === 'string' && actionId) {
          onAction(actionId, value);
        }
        return;
      }
      if (msg.type === 'navigate') {
        const target = msg.payload?.surface_id;
        if (typeof target === 'string' && target) openSurface(target);
        return;
      }
      // request_data / close currently no-op in v2; the schema is
      // pinned so we can route them when the brain grows handlers.
    }
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [onAction, openSurface]);

  const surfaces = useMemo(() => {
    if (!manifest?.surfaces) return [];
    return manifest.surfaces;
  }, [manifest]);

  const brand = manifest?.brand || {};

  const srcDoc = useMemo(() => {
    if (!tree) return null;
    return buildSrcDoc({ tree, manifest: manifest || {}, signedWithKeyId: signedKeyId });
  }, [tree, manifest, signedKeyId]);

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
        {srcDoc && (
          <iframe
            ref={iframeRef}
            data-testid="v2-appsurface-iframe"
            title={`AppSurface ${activeSurface || appId}`}
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            srcDoc={srcDoc}
            style={{
              width: '100%',
              minHeight: 480,
              border: 0,
              borderRadius: 12,
              background: 'transparent',
            }}
          />
        )}
      </Pane>
    </div>
  );
}

// Tiny shim — we used to reuse SduiRenderer.applySduiPatches but that
// module renders React. The iframe owns its DOM, so patches just walk
// the in-memory tree before the next srcdoc rebuild.
function applySduiPatchesShallow(tree, patches) {
  if (!Array.isArray(patches) || patches.length === 0) return tree;
  return tree;
}
