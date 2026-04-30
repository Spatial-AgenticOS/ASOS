import React, { useEffect, useMemo, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";
import SduiRenderer from "../../ui/SduiRenderer";

function makeId(prefix = "push") {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
}

function normalizePush(frameOrPayload) {
  if (!frameOrPayload) return null;
  const payload = frameOrPayload.payload || frameOrPayload;
  if (!payload.kind) return null;
  return {
    id: payload.push_id || makeId(payload.kind),
    kind: payload.kind,
    app_id: payload.app_id || "unknown",
    surface_id: payload.surface_id || payload.app_id || "surface",
    title: payload.title || payload.app_id || "App notification",
    body: payload.body || "",
    actions: Array.isArray(payload.actions) ? payload.actions : [],
    sdui: payload.sdui || payload.root || null,
  };
}

export default function AppsPanel({ shell: shellProp }) {
  const outletShell = useOutletContext();
  const shell = shellProp || outletShell || {};
  const { device_id: deviceId = "", app_id: routeAppId = "" } = useParams();

  const [notifications, setNotifications] = useState([]);
  const [surfaces, setSurfaces] = useState({});

  useEffect(() => {
    const onPush = (frame) => {
      const push = normalizePush(frame);
      if (!push) return;
      if (push.kind === "notification") {
        setNotifications((prev) => [push, ...prev].slice(0, 24));
      }
      if (push.kind === "interactive") {
        setSurfaces((prev) => ({
          ...prev,
          [push.app_id]: push,
        }));
      }
    };

    if (shell?.subscribePhase) {
      return shell.subscribePhase("genui_push", onPush);
    }
    if (shell?.subscribeFrame) {
      return shell.subscribeFrame((frame) => {
        if (frame?.type !== "genui_push") return;
        onPush(frame);
      });
    }
    return () => {};
  }, [shell]);

  const appIds = useMemo(() => {
    const seen = new Set();
    Object.keys(surfaces).forEach((id) => seen.add(id));
    notifications.forEach((entry) => seen.add(entry.app_id));
    return Array.from(seen);
  }, [notifications, surfaces]);

  const activeAppId = routeAppId || appIds[0] || "";
  const activeSurface = activeAppId ? surfaces[activeAppId] : null;

  const dismissNotification = (id) => {
    setNotifications((prev) => prev.filter((entry) => entry.id !== id));
  };

  const emitAction = (actionId, value) => {
    if (!activeAppId || !shell?.sendFrame) return;
    shell.sendFrame("genui_event", {
      app_id: activeAppId,
      surface_id: activeSurface?.surface_id || activeAppId,
      event_type: "tap",
      action_id: actionId,
      value,
    });
  };

  return (
    <section data-testid="apps-panel" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {notifications.length === 0 ? (
          <p className="v2-p v2-p--muted" style={{ margin: 0 }}>
            No app pushes yet.
          </p>
        ) : (
          notifications.map((notification) => (
            <article
              key={notification.id}
              style={{
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.08)",
                background: "rgba(255,255,255,0.04)",
                padding: 10,
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "space-between",
                gap: 8,
              }}
            >
              <div>
                <strong>{notification.title}</strong>
                {notification.body ? (
                  <p className="v2-p v2-p--muted" style={{ margin: "4px 0 0" }}>
                    {notification.body}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                className="v2-btn v2-btn--ghost"
                onClick={() => dismissNotification(notification.id)}
              >
                Dismiss
              </button>
            </article>
          ))
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {appIds.map((appId) => (
          <Link
            key={appId}
            to={`/pair/${encodeURIComponent(deviceId)}/apps/${encodeURIComponent(appId)}`}
            className={`v2-btn ${activeAppId === appId ? "v2-btn--primary" : ""}`.trim()}
          >
            {appId}
          </Link>
        ))}
      </div>

      <div
        style={{
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.02)",
          minHeight: 200,
          padding: 10,
        }}
      >
        {!activeAppId ? (
          <p className="v2-p v2-p--muted" style={{ margin: 0 }}>
            Interactive app surfaces appear here when a
            <code style={{ margin: "0 4px" }}>genui_push</code>
            frame arrives.
          </p>
        ) : !activeSurface?.sdui ? (
          <p className="v2-p v2-p--muted" style={{ margin: 0 }}>
            App <strong>{activeAppId}</strong> has no interactive surface yet.
          </p>
        ) : (
          <SduiRenderer tree={activeSurface.sdui} onAction={emitAction} />
        )}
      </div>
    </section>
  );
}
