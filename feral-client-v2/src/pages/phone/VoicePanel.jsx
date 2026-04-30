import React, { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import StatusDot from "../../ui/StatusDot";

function transcriptLineFromFrame(frame) {
  const payload = frame?.payload || {};
  if (typeof payload.transcript === "string" && payload.transcript.trim()) {
    return payload.transcript.trim();
  }
  if (payload.channel === "voice" && typeof payload.text === "string" && payload.text.trim()) {
    return payload.text.trim();
  }
  return "";
}

export default function VoicePanel({ shell: shellProp }) {
  const outletShell = useOutletContext();
  const shell = shellProp || outletShell || {};
  const [toggleMic, setToggleMic] = useState(false);
  const [holdMic, setHoldMic] = useState(false);
  const [vadActive, setVadActive] = useState(false);
  const [transcript, setTranscript] = useState([]);

  const micActive = toggleMic || holdMic;

  useEffect(() => {
    if (!shell?.subscribeFrame) return () => {};
    return shell.subscribeFrame((frame) => {
      if (frame?.type === "voice_vad") {
        setVadActive(!!frame?.payload?.speaking);
        return;
      }
      if (frame?.type !== "chat_response") return;
      const line = transcriptLineFromFrame(frame);
      if (!line) return;
      setTranscript((prev) => [{
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        text: line,
      }, ...prev].slice(0, 20));
    });
  }, [shell]);

  useEffect(() => {
    const node = shell?.node;
    if (!node) return;
    if (micActive) {
      node.startMic?.().catch(() => {});
      setVadActive(true);
      return;
    }
    node.stopMic?.().catch(() => {});
    setVadActive(false);
  }, [micActive, shell]);

  const interrupt = () => {
    shell?.sendFrame?.("voice_interrupt", {
      stream_id: `voice-${shell.deviceId || "session"}`,
      reason: "user_interrupt",
    });
  };

  const vadTone = useMemo(() => (vadActive ? "live" : "off"), [vadActive]);

  return (
    <section data-testid="voice-panel" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <StatusDot tone={vadTone} pulse={vadActive} label={`VAD ${vadActive ? "active" : "idle"}`} />
        <span>VAD {vadActive ? "active" : "idle"}</span>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          className={`v2-btn ${toggleMic ? "v2-btn--primary" : ""}`.trim()}
          aria-pressed={toggleMic}
          onClick={() => setToggleMic((prev) => !prev)}
        >
          {toggleMic ? "Tap mic on" : "Tap mic off"}
        </button>
        <button
          type="button"
          className={`v2-btn ${holdMic ? "v2-btn--primary" : ""}`.trim()}
          onMouseDown={() => setHoldMic(true)}
          onMouseUp={() => setHoldMic(false)}
          onMouseLeave={() => setHoldMic(false)}
          onTouchStart={() => setHoldMic(true)}
          onTouchEnd={() => setHoldMic(false)}
        >
          Hold to talk
        </button>
        <button
          type="button"
          className="v2-btn"
          onClick={interrupt}
        >
          Interrupt
        </button>
      </div>
      <div
        style={{
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.02)",
          minHeight: 120,
          padding: 10,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {transcript.length === 0 ? (
          <p className="v2-p v2-p--muted" style={{ margin: 0 }}>
            Voice transcripts appear here as responses arrive.
          </p>
        ) : (
          transcript.map((line) => (
            <div key={line.id}>{line.text}</div>
          ))
        )}
      </div>
    </section>
  );
}
