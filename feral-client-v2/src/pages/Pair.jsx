/**
 * Pair — unauthenticated landing page.
 *
 * The QR a user scans on their phone encodes <origin>/pair?t=<TOKEN>.
 * Opening that URL (on ANY phone, no app needed) renders this page.
 * On pair success we claim a runtime phone bearer, persist it in IndexedDB,
 * then instantiate BrowserNode which connects to /v1/node using that bearer,
 * registers as a browser_node, and starts
 * streaming sensors back to the Brain.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Smartphone, ShieldCheck, Zap, AlertTriangle } from "lucide-react";
import { Navigate } from "react-router-dom";
import BrowserNode from "../node/BrowserNode";
import {
  clearPhoneBearer,
  getLatestPhoneBearer,
  setPhoneBearer,
} from "../lib/phoneBearerStore";

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
  const [isBootstrapped, setIsBootstrapped] = useState(false);
  const [resumeRecord, setResumeRecord] = useState(null);
  const [permissions, setPermissions] = useState({
    location: true,
    camera: false,
    mic: false,
  });
  const [node, setNode] = useState(null);
  const connectInFlightRef = useRef(false);

  useEffect(() => {
    return () => {
      if (node) node.stop().catch(() => {});
    };
  }, [node]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const existing = await getLatestPhoneBearer();
        if (cancelled) return;
        if (
          existing
          && existing.phone_bearer
          && existing.paired_device_id
          && existing.pair_claim_marker
        ) {
          setResumeRecord(existing);
          setPhase("restoring");
        } else {
          setPhase("idle");
        }
      } catch (err) {
        if (cancelled) return;
        setError(err?.message || String(err));
        setPhase(token ? "idle" : "failed");
      } finally {
        if (!cancelled) setIsBootstrapped(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const connectWithBearer = useCallback(async (bearer, onPhase) => {
    const n = new BrowserNode({
      token: bearer,
      onPhase: (p) => {
        setPhase(p);
        onPhase?.(p);
      },
      onError: (e) => setError(e?.message || String(e)),
    });
    await n.connect();
    await n.startSensors(permissions);
    setNode(n);
    setPhase("live");
    return n;
  }, [permissions]);

  useEffect(() => {
    if (!isBootstrapped || !resumeRecord || node || connectInFlightRef.current) return;
    if (!resumeRecord.phone_bearer || !resumeRecord.paired_device_id) return;

    let cancelled = false;
    connectInFlightRef.current = true;
    setError(null);
    setPhase("restoring");

    connectWithBearer(resumeRecord.phone_bearer)
      .catch(async (err) => {
        if (cancelled) return;
        setError(err?.message || String(err));
        await clearPhoneBearer(resumeRecord.paired_device_id);
        setResumeRecord(null);
        setPhase(token ? "idle" : "failed");
      })
      .finally(() => {
        connectInFlightRef.current = false;
      });

    return () => {
      cancelled = true;
    };
  }, [connectWithBearer, isBootstrapped, node, resumeRecord, token]);

  const canPair = !!token && isBootstrapped && !resumeRecord && phase === "idle";

  const pair = useCallback(async () => {
    if (!canPair || connectInFlightRef.current) return;
    setError(null);
    setPhase("claiming");
    let saved = null;
    try {
      const claimRes = await fetch(
        new URL("/api/devices/pair/complete", window.location.origin).toString(),
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ token, kind: "browser_node_v2" }),
        },
      );
      if (!claimRes.ok) {
        const details = await claimRes.text().catch(() => "");
        throw new Error(
          `pair claim failed (${claimRes.status})${details ? `: ${details}` : ""}`,
        );
      }
      const claim = await claimRes.json();
      const phoneBearer = claim.phone_bearer || "";
      const pairedDeviceId = claim.paired_device_id || claim.device_id || "";
      const pairClaimMarker = claim.pair_claim_marker || "";
      if (!phoneBearer || !pairedDeviceId || !pairClaimMarker) {
        throw new Error("pair claim response missing phone bearer metadata");
      }

      saved = await setPhoneBearer({
        paired_device_id: pairedDeviceId,
        phone_bearer: phoneBearer,
        pair_claim_marker: pairClaimMarker,
      });
      setResumeRecord(saved);

      connectInFlightRef.current = true;
      await connectWithBearer(phoneBearer);
      connectInFlightRef.current = false;
    } catch (err) {
      connectInFlightRef.current = false;
      if (saved?.paired_device_id) {
        await clearPhoneBearer(saved.paired_device_id);
      }
      setResumeRecord(null);
      setError(err?.message || String(err));
      setPhase("idle");
    }
  }, [canPair, connectWithBearer, token]);

  const disconnect = useCallback(async () => {
    if (node) {
      await node.stop();
      setNode(null);
    }
    if (resumeRecord?.paired_device_id) {
      await clearPhoneBearer(resumeRecord.paired_device_id);
    }
    setResumeRecord(null);
    setPhase(token ? "idle" : "failed");
  }, [node, resumeRecord, token]);

  if (!isBootstrapped) {
    return (
      <Frame>
        <Card>
          <Header icon={Smartphone} title="Restoring pairing" />
          <p>Checking for an existing paired session on this device...</p>
        </Card>
      </Frame>
    );
  }

  if (!token && !resumeRecord) {
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

  const isLive = phase === "live" || phase === "registered"
    || phase === "acknowledged" || phase === "mic_streaming"
    || phase === "camera_streaming" || phase === "voice_config";

  if (resumeRecord && !isLive) {
    return (
      <Frame>
        <Card>
          <Header icon={Smartphone} title="Restoring paired session" />
          <p>
            Reconnecting to your paired FERAL session using the saved
            phone bearer.
          </p>
          {error && (
            <div style={errorBox}>
              <AlertTriangle size={13} aria-hidden="true" /> {error}
            </div>
          )}
        </Card>
      </Frame>
    );
  }

  const toggleMic = async () => {
    if (!node) return;
    if (permissions.mic) {
      await node.stopMic();
      setPermissions((p) => ({ ...p, mic: false }));
    } else {
      await node.startMic();
      setPermissions((p) => ({ ...p, mic: true }));
    }
  };

  const toggleCamera = async () => {
    if (!node) return;
    if (permissions.camera) {
      await node.stopCamera();
      setPermissions((p) => ({ ...p, camera: false }));
    } else {
      await node.startCamera();
      setPermissions((p) => ({ ...p, camera: true }));
    }
  };

  if (isLive) {
    const pairedDeviceId = resumeRecord?.paired_device_id
      || (typeof localStorage !== "undefined" ? localStorage.getItem("feral.paired_device_id") : "");
    if (pairedDeviceId) {
      return <Navigate to={`/pair/${encodeURIComponent(pairedDeviceId)}/chat`} replace />;
    }

    return (
      <Frame>
        <Card>
          <Header icon={CheckCircle2} title="Paired" tone="live" />
          <p>
            This device is now a live FERAL node. Toggle individual
            streams below — each goes live only while you flip it on.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
            <LiveRow
              label="Location"
              active={permissions.location}
              color="#30D158"
            />
            <LiveRow
              label="Microphone"
              active={permissions.mic}
              color="#FF9F0A"
              onToggle={toggleMic}
            />
            <LiveRow
              label="Camera"
              active={permissions.camera}
              color="#FF453A"
              onToggle={toggleCamera}
            />
          </div>
          <p style={{ marginTop: 12, fontSize: 12, opacity: 0.6 }}>
            Mic streams PCM16 @ 16 kHz as
            <code style={{ margin: "0 4px" }}>audio_chunk</code>
            frames; camera streams
            <code style={{ margin: "0 4px" }}>frame</code>
            jpeg payloads every ~750 ms.
          </p>
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

function LiveRow({ label, active, color, onToggle }) {
  return (
    <div style={toggleRow}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 8, height: 8, borderRadius: "50%",
            background: active ? color : "rgba(255,255,255,0.3)",
            boxShadow: active ? `0 0 8px ${color}` : "none",
            animation: active ? "v2-pulse 1.4s ease-in-out infinite" : "none",
          }}
        />
        <span>{label}</span>
      </span>
      {onToggle ? (
        <button
          type="button"
          onClick={onToggle}
          style={{
            ...btnSecondary,
            marginTop: 0,
            padding: "6px 12px",
            background: active ? "rgba(255,69,58,0.2)" : "rgba(255,255,255,0.06)",
          }}
        >
          {active ? "Stop" : "Start"}
        </button>
      ) : (
        <span style={{ fontSize: 12, opacity: 0.6 }}>{active ? "live" : "off"}</span>
      )}
    </div>
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
