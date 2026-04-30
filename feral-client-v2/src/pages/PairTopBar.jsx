import React from "react";
import StatusDot from "../ui/StatusDot";

const STATUS_META = {
  connected: { tone: "live", label: "Connected" },
  registered: { tone: "live", label: "Registered" },
  acknowledged: { tone: "live", label: "Ready" },
  connecting: { tone: "warn", label: "Connecting" },
  restoring: { tone: "warn", label: "Restoring" },
  closed: { tone: "off", label: "Disconnected" },
  failed: { tone: "error", label: "Failed" },
};

function getStatusMeta(status) {
  if (!status) return { tone: "neutral", label: "Idle" };
  return STATUS_META[status] || { tone: "neutral", label: status };
}

export default function PairTopBar({
  deviceId,
  status,
  modeLabel,
  onDisconnect,
}) {
  const meta = getStatusMeta(status);
  return (
    <header
      data-testid="pair-top-bar"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <StatusDot
          tone={meta.tone}
          pulse={meta.tone === "live" || meta.tone === "warn"}
          label={`Pair session status: ${meta.label}`}
        />
        <strong>{deviceId}</strong>
        <span className={`v2-chip ${meta.tone === "error" ? "v2-chip--error" : meta.tone === "warn" ? "v2-chip--warn" : "v2-chip--live"}`}>
          {meta.label}
        </span>
      </div>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <span className="v2-chip v2-chip--muted">{modeLabel}</span>
        <button
          type="button"
          className="v2-btn"
          onClick={onDisconnect}
        >
          Disconnect
        </button>
      </div>
    </header>
  );
}
