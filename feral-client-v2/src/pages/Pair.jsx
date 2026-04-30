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

  // pair-pin-confirm PR — PIN second factor.
  const [pinRequired, setPinRequired] = useState(null); // null = not yet checked
  const [pinLength, setPinLength] = useState(4);
  const [pinInput, setPinInput] = useState("");
  const [pinVerified, setPinVerified] = useState(false);
  const [pinBusy, setPinBusy] = useState(false);

  useEffect(() => {
    return () => {
      if (node) node.stop().catch(() => {});
    };
  }, [node]);

  // On mount, ask the brain whether THIS token requires a PIN. The
  // /check endpoint is open-listed and only leaks the PIN-or-not
  // status, which is harmless given the phone already has the token.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `/api/devices/pair/check?t=${encodeURIComponent(token)}`,
          { credentials: "same-origin" },
        );
        if (!r.ok) return;
        const data = await r.json();
        if (cancelled) return;
        setPinRequired(Boolean(data?.pin_required));
        if (data?.pin_length) setPinLength(Number(data.pin_length));
      } catch {
        // Silent; pair can still try and the brain will reject if needed.
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  const verifyPin = useCallback(async () => {
    if (!token || !pinInput) return;
    setPinBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/devices/pair/verify_pin", {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ token, pin: pinInput }),
      });
      if (r.ok) {
        setPinVerified(true);
        return;
      }
      const data = await r.json().catch(() => ({}));
      const code = data?.detail?.code;
      if (code === "wrong_pin") {
        setError("Wrong PIN. Check the numbers shown on the FERAL Mac.");
      } else if (code === "exhausted") {
        setError("Too many wrong attempts. Ask the FERAL Mac to generate a new pair URL.");
      } else if (code === "expired") {
        setError("This pair URL has expired. Ask for a fresh one.");
      } else if (code === "no_pin_required") {
        // Edge: brain says no PIN; just proceed.
        setPinVerified(true);
      } else {
        setError(`Could not verify PIN (${r.status}).`);
      }
      setPinInput("");
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setPinBusy(false);
    }
  }, [token, pinInput]);

  const pinGateOpen = pinRequired === false || pinVerified;
  const canPair = !!token && phase === "idle" && pinGateOpen;

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

  const isLive = phase === "live" || phase === "registered"
    || phase === "acknowledged" || phase === "mic_streaming"
    || phase === "camera_streaming" || phase === "voice_config";

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

        {/* PIN second-factor gate (pair-pin-confirm PR). When the
            pair URL was issued with require_pin=true, this block
            appears BEFORE the permission toggles. The user must
            enter the 4-digit PIN shown on the FERAL Mac dashboard
            before "Pair this device" becomes enabled. */}
        {pinRequired === true && !pinVerified && (
          <div style={{ marginTop: 14 }} data-testid="pair-pin-form">
            <div style={pinHelpBox}>
              <div style={{ display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <ShieldCheck size={13} aria-hidden="true" />
                <strong>Enter the PIN shown on FERAL</strong>
              </div>
              <p style={{ margin: "0 0 10px", fontSize: 13, opacity: 0.8 }}>
                The FERAL Mac is showing a {pinLength}-digit number.
                Type it below before this device can pair.
              </p>
              <input
                type="text"
                inputMode="numeric"
                pattern={`[0-9]{${pinLength}}`}
                maxLength={pinLength}
                placeholder={"•".repeat(pinLength)}
                value={pinInput}
                onChange={(e) => setPinInput(e.target.value.replace(/[^0-9]/g, ""))}
                disabled={pinBusy}
                style={pinInputStyle}
                data-testid="pair-pin-input"
                autoFocus
              />
              <button
                type="button"
                onClick={verifyPin}
                disabled={pinBusy || pinInput.length !== pinLength}
                style={{ ...btnPrimary, marginLeft: 8 }}
                data-testid="pair-pin-submit"
              >
                {pinBusy ? "Checking…" : "Verify"}
              </button>
            </div>
          </div>
        )}

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
            data-testid="pair-pair-button"
          >
            <Zap size={14} aria-hidden="true" />{" "}
            {phase === "idle"
              ? (pinRequired === true && !pinVerified
                  ? "Enter PIN to continue"
                  : "Pair this device")
              : phase}
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

const pinHelpBox = {
  padding: 14,
  borderRadius: 12,
  border: "1px solid rgba(255, 213, 87, 0.3)",
  background: "rgba(255, 213, 87, 0.06)",
  color: "#FFE9A7",
};

const pinInputStyle = {
  fontSize: 24,
  letterSpacing: "0.4em",
  padding: "10px 14px",
  width: "8.5em",
  textAlign: "center",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.16)",
  background: "rgba(0,0,0,0.3)",
  color: "white",
  fontFamily: "ui-monospace, SFMono-Regular, monospace",
  outline: "none",
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
