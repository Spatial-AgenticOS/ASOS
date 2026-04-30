import React, { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

function extractVisionResult(frame) {
  const payload = frame?.payload || {};
  if (payload.channel && payload.channel !== "vision_ask") return "";
  if (typeof payload.text === "string" && payload.text.trim()) return payload.text.trim();
  if (typeof payload.message === "string" && payload.message.trim()) return payload.message.trim();
  return "";
}

export default function VisionAskPanel({ shell: shellProp }) {
  const outletShell = useOutletContext();
  const shell = shellProp || outletShell || {};
  const [cameraReady, setCameraReady] = useState(false);
  const [captures, setCaptures] = useState(0);
  const [prompt, setPrompt] = useState("what is this?");
  const [result, setResult] = useState("");

  useEffect(() => {
    if (!shell?.subscribeFrame) return () => {};
    return shell.subscribeFrame((frame) => {
      if (frame?.type !== "chat_response") return;
      const text = extractVisionResult(frame);
      if (!text) return;
      setResult(text);
    });
  }, [shell]);

  const toggleCameraPermission = async () => {
    const node = shell?.node;
    if (!node) return;
    if (cameraReady) {
      await node.stopCamera?.().catch(() => {});
      setCameraReady(false);
      return;
    }
    await node.startCamera?.().catch(() => {});
    setCameraReady(true);
  };

  const captureFrame = () => {
    if (!cameraReady || !shell?.node?._pushCameraFrame) return;
    shell.node._pushCameraFrame();
    setCaptures((prev) => prev + 1);
  };

  const askVision = () => {
    const text = prompt.trim();
    if (!text || !shell?.sendFrame) return;
    shell.sendFrame("chat_request", {
      session_id: `vision-${shell.deviceId || "session"}`,
      text,
      channel: "vision_ask",
      reply_mode: "final",
      reply_to: null,
    });
  };

  return (
    <section data-testid="vision-panel" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="v2-btn" onClick={toggleCameraPermission}>
          {cameraReady ? "Stop camera" : "Allow camera"}
        </button>
        <button
          type="button"
          className="v2-btn"
          onClick={captureFrame}
          disabled={!cameraReady}
        >
          Capture frame ({captures})
        </button>
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          className="v2-input"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="what is this?"
          aria-label="Vision prompt"
        />
        <button type="button" className="v2-btn v2-btn--primary" onClick={askVision}>
          Ask
        </button>
      </div>

      <div
        style={{
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.02)",
          minHeight: 120,
          padding: 10,
        }}
      >
        {result ? (
          <p style={{ margin: 0 }}>{result}</p>
        ) : (
          <p className="v2-p v2-p--muted" style={{ margin: 0 }}>
            Capture a frame, ask a question, and the answer will appear here.
          </p>
        )}
      </div>
    </section>
  );
}
