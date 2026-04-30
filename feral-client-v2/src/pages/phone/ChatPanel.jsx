import React, { useEffect, useMemo, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";

function extractChatText(payload) {
  if (!payload) return "";
  if (typeof payload.text === "string" && payload.text.trim()) return payload.text.trim();
  if (typeof payload.message === "string" && payload.message.trim()) return payload.message.trim();
  if (typeof payload.content === "string" && payload.content.trim()) return payload.content.trim();
  return "";
}

function makeMessage(role, text) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    role,
    text,
  };
}

export default function ChatPanel({ shell: shellProp }) {
  const outletShell = useOutletContext();
  const shell = shellProp || outletShell || {};
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState([]);
  const historyRef = useRef(null);

  const canSend = useMemo(() => {
    return !!shell?.sendFrame && draft.trim().length > 0;
  }, [draft, shell]);

  useEffect(() => {
    if (!shell?.subscribeFrame) return () => {};
    return shell.subscribeFrame((frame) => {
      if (frame?.type !== "chat_response") return;
      const text = extractChatText(frame.payload);
      if (!text) return;
      setMessages((prev) => [...prev, makeMessage("assistant", text)]);
    });
  }, [shell]);

  useEffect(() => {
    if (!historyRef.current) return;
    historyRef.current.scrollTop = historyRef.current.scrollHeight;
  }, [messages]);

  const send = () => {
    const text = draft.trim();
    if (!text || !shell?.sendFrame) return;
    shell.sendFrame("chat_request", {
      session_id: `phone-${shell.deviceId || "session"}`,
      text,
      reply_mode: "stream",
      channel: "chat",
      reply_to: null,
    });
    setMessages((prev) => [...prev, makeMessage("user", text)]);
    setDraft("");
  };

  const onSubmit = (event) => {
    event.preventDefault();
    send();
  };

  return (
    <section data-testid="chat-panel" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div
        ref={historyRef}
        aria-live="polite"
        style={{
          minHeight: 220,
          maxHeight: 360,
          overflowY: "auto",
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "rgba(255,255,255,0.02)",
          padding: 10,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {messages.length === 0 ? (
          <p className="v2-p v2-p--muted" style={{ margin: 0 }}>
            Ask anything to the paired brain. Responses stream back here as
            <code style={{ margin: "0 4px" }}>chat_response</code>
            frames.
          </p>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              style={{
                alignSelf: message.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "85%",
                padding: "8px 10px",
                borderRadius: 10,
                background: message.role === "user"
                  ? "rgba(10,132,255,0.24)"
                  : "rgba(255,255,255,0.08)",
                border: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              {message.text}
            </div>
          ))
        )}
      </div>
      <form onSubmit={onSubmit} style={{ display: "flex", gap: 8 }}>
        <input
          className="v2-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Type a message"
          aria-label="Chat input"
        />
        <button
          type="submit"
          className="v2-btn v2-btn--primary"
          disabled={!canSend}
        >
          Send
        </button>
      </form>
    </section>
  );
}
