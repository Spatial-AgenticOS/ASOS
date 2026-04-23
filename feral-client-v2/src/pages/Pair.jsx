/**
 * Pair — unauthenticated landing page.
 *
 * The QR a user scans on their phone encodes <origin>/pair?t=<TOKEN>.
 * Opening that URL (on ANY phone, no app needed) renders this page.
 * One tap on "Pair this phone" instantiates BrowserNode which opens
 * /v1/node?api_key=<TOKEN>, registers as a browser_node, and starts
 * streaming sensors back to the Brain.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Smartphone, ShieldCheck, Zap, AlertTriangle } from "lucide-react";
import BrowserNode from "../node/BrowserNode";

function useToken() {
  return useMemo(() => {
    if (typeof window === "undefined") return "";
    const url = new URL(window.location.href);
    return url.searchParams.get("t") || url.searchParams.get("token") || "";
  }, []);
}

export default function Pair() {
  const token = useToken();
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState(null);
  const [permissions, setPermissions] = useState({
    location: true,
    camera: false,
    mic: false,
  });
  const [node, setNode] = useState(null);

  useEffect(() => {
    return () => {
      if (node) node.stop().catch(() => {});
    };
  }, [node]);

  const canPair = !!token && phase === "idle";

  const pair = useCallback(async () => {
    if (!canPair) return;
    setError(null);
    setPhase("connecting");
    try {
      const n = new BrowserNode({
        token,
        onPhase: (p) => setPhase(p),
        onError: (e) => setError(e?.message || String(e)),
      });
      await n.connect();
      await n.startSensors(permissions);
      setNode(n);
      setPhase("live");
    } catch (err) {
      setError(err?.message || String(err));
      setPhase("failed");
    }
  }, [canPair, token, permissions]);

  const disconnect = useCallback(async () => {
    if (node) {
      await node.stop();
      setNode(null);
    }
    setPhase("idle");
  }, [node]);

  if (!token) {
    return (
      <Frame>
        <Card>
          <Header icon={AlertTriangle} title="No pairing token" tone="warn" />
          <p>
            This page expects a <code>?t=TOKEN</code> query string. The
            QR you scanned either didn't include one, or the token has
            already been claimed.
          </p>
          <p style={{ marginTop: 10, fontSize: 13, opacity: 0.7 }}>
            Reopen the Pair modal on the Brain, scan the new QR, and try
            again.
          </p>
        </Card>
      </Frame>
    );
  }

  if (phase === "live" || phase === "registered" || phase === "acknowledged") {
    return (
      <Frame>
        <Card>
          <Header icon={CheckCircle2} title="Paired" tone="live" />
          <p>
            This device is now a live FERAL node. Sensor streams you
            allowed are flowing to the Brain.
          </p>
          <ul style={bulletList}>
            <li>Location: {permissions.location ? "live" : "disabled"}</li>
            <li>Camera: {permissions.camera ? "live" : "disabled"}</li>
            <li>Microphone: {permissions.mic ? "live" : "disabled"}</li>
          </ul>
          <button
            type="button"
            onClick={disconnect}
            style={btnSecondary}
          >
            Disconnect
          </button>
        </Card>
      </Frame>
    );
  }

  return (
    <Frame>
      <Card>
        <Header icon={Smartphone} title="Pair this device" />
        <p>
          You're about to make this device a real FERAL node. No app
          install. Sensors stream only while this page is open and you
          tapped "Allow" below.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
          <PermissionToggle
            label="Share location"
            on={permissions.location}
            onChange={(v) => setPermissions((p) => ({ ...p, location: v }))}
          />
          <PermissionToggle
            label="Share camera (on request only)"
            on={permissions.camera}
            onChange={(v) => setPermissions((p) => ({ ...p, camera: v }))}
          />
          <PermissionToggle
            label="Share microphone (on request only)"
            on={permissions.mic}
            onChange={(v) => setPermissions((p) => ({ ...p, mic: v }))}
          />
        </div>

        <div style={{ marginTop: 18, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={pair}
            disabled={!canPair}
            style={btnPrimary}
          >
            <Zap size={14} aria-hidden="true" /> {phase === "idle" ? "Pair this device" : phase}
          </button>
        </div>

        {error && (
          <div style={errorBox}>
            <AlertTriangle size={13} aria-hidden="true" /> {error}
          </div>
        )}

        <p style={{ marginTop: 14, fontSize: 12, opacity: 0.65, display: "inline-flex", alignItems: "center", gap: 6 }}>
          <ShieldCheck size={12} aria-hidden="true" />
          Token {token.slice(0, 8)}… &middot; encoded in the QR you scanned.
        </p>
      </Card>
    </Frame>
  );
}

function Frame({ children }) {
  return (
    <div style={frameStyle}>
      <div style={{ maxWidth: 440, width: "100%" }}>{children}</div>
    </div>
  );
}

function Card({ children }) {
  return <div style={cardStyle}>{children}</div>;
}

function Header({ icon: Icon, title, tone }) {
  const color = tone === "live" ? "#30D158" : tone === "warn" ? "#FFD60A" : "#F5F5F7";
  return (
    <header style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
      <div style={{ ...iconStyle, color }}>
        <Icon size={18} aria-hidden="true" />
      </div>
      <h1 style={{ margin: 0, fontSize: 22, letterSpacing: "-0.01em" }}>{title}</h1>
    </header>
  );
}

function PermissionToggle({ label, on, onChange }) {
  return (
    <label style={toggleRow}>
      <span>{label}</span>
      <input
        type="checkbox"
        checked={!!on}
        onChange={(e) => onChange(e.target.checked)}
        style={{ width: 20, height: 20 }}
      />
    </label>
  );
}

const frameStyle = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 24,
  background: "linear-gradient(180deg, #1F1F27 0%, #0F0F15 100%)",
  color: "#F5F5F7",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', 'Inter', 'Segoe UI', Roboto, sans-serif",
};

const cardStyle = {
  padding: 20,
  borderRadius: 20,
  background: "rgba(28, 28, 34, 0.7)",
  backdropFilter: "saturate(1.8) blur(40px)",
  border: "1px solid rgba(255, 255, 255, 0.1)",
  boxShadow: "0 12px 36px rgba(0,0,0,0.45)",
};

const iconStyle = {
  width: 32,
  height: 32,
  borderRadius: 10,
  background: "rgba(255,255,255,0.06)",
  display: "grid",
  placeItems: "center",
};

const btnPrimary = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "10px 16px",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "#0A84FF",
  color: "white",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
};

const btnSecondary = {
  padding: "8px 14px",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(255,255,255,0.06)",
  color: "white",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  marginTop: 14,
};

const toggleRow = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "10px 12px",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.08)",
  background: "rgba(255,255,255,0.04)",
  fontSize: 14,
};

const bulletList = {
  margin: "10px 0 14px",
  paddingLeft: 18,
  fontSize: 13,
  lineHeight: 1.6,
  color: "rgba(255,255,255,0.75)",
};

const errorBox = {
  marginTop: 12,
  padding: "8px 12px",
  borderRadius: 10,
  background: "rgba(255, 69, 58, 0.14)",
  border: "1px solid rgba(255, 69, 58, 0.3)",
  color: "#FFB2AB",
  fontSize: 13,
  display: "flex",
  alignItems: "center",
  gap: 6,
};
