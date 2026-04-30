import React from "react";
import { useOutletContext } from "react-router-dom";
import StatusDot from "../../ui/StatusDot";

const APPROVAL_PLACEHOLDERS = [
  { id: "camera.shutter", scope: "allow once" },
  { id: "device.vibrate", scope: "allow for this app" },
  { id: "peripheral.scan", scope: "never for this device" },
];

function PermissionRow({ label, value, onChange }) {
  return (
    <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
      <span>{label}</span>
      <input
        type="checkbox"
        checked={!!value}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

export default function SettingsPanel({ shell: shellProp }) {
  const outletShell = useOutletContext();
  const shell = shellProp || outletShell || {};
  const permissions = shell.permissions || {};
  const logs = shell.logs || [];

  return (
    <section data-testid="settings-panel" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <StatusDot tone={shell.isConnected ? "live" : "warn"} pulse={shell.isConnected} />
        <span>{shell.isConnected ? "Connected to brain" : "Connection not ready"}</span>
      </div>

      <div
        style={{
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.02)",
          padding: 10,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <strong>Sensor permissions</strong>
        <PermissionRow
          label="Location"
          value={permissions.location}
          onChange={(next) => shell.setPermission?.("location", next)}
        />
        <PermissionRow
          label="Camera"
          value={permissions.camera}
          onChange={(next) => shell.setPermission?.("camera", next)}
        />
        <PermissionRow
          label="Microphone"
          value={permissions.mic}
          onChange={(next) => shell.setPermission?.("mic", next)}
        />
      </div>

      <div
        style={{
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.02)",
          padding: 10,
        }}
      >
        <strong>Agent action approvals</strong>
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
          {APPROVAL_PLACEHOLDERS.map((entry) => (
            <li key={entry.id}>
              <code>{entry.id}</code> — {entry.scope}
            </li>
          ))}
        </ul>
      </div>

      <div
        style={{
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.02)",
          padding: 10,
          maxHeight: 220,
          overflowY: "auto",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 12,
          lineHeight: 1.4,
        }}
      >
        <strong style={{ fontFamily: "inherit", fontSize: 13 }}>Debug log</strong>
        {logs.length === 0 ? (
          <div className="v2-p v2-p--muted" style={{ marginTop: 8 }}>
            No events captured yet.
          </div>
        ) : (
          <pre style={{ margin: "8px 0 0", whiteSpace: "pre-wrap" }}>
            {logs.map((entry) => `[${entry.at}] ${entry.event}`).join("\n")}
          </pre>
        )}
      </div>

      <div>
        <button type="button" className="v2-btn" onClick={shell.disconnect}>
          Disconnect
        </button>
      </div>
    </section>
  );
}
