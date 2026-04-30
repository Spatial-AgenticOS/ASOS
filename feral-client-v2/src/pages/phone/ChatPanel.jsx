import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Send } from 'lucide-react';
import { useWebSpeech } from '../../hooks/useWebSpeech';

const LONG_PRESS_MS = 400;

function newId() {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

export default function ChatPanel({ shell, messages: propMessages, onSend }) {
  const [localMessages, setLocalMessages] = useState([
    { id: 'hello', role: 'assistant', text: 'How can I help?' },
  ]);
  const messages = propMessages || localMessages;
  const [input, setInput] = useState('');
  const [voiceFullscreenOpen, setVoiceFullscreenOpen] = useState(false);
  const [dictationError, setDictationError] = useState(null);

  const longPressTimerRef = useRef(null);
  const longPressTriggeredRef = useRef(false);
  const bottomRef = useRef(null);

  const speech = useWebSpeech({ continuous: false, interimResults: true });
  const VoiceFullscreenRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mod = await import(/* @vite-ignore */ './VoiceFullscreen');
        if (!cancelled) VoiceFullscreenRef.current = mod.default || mod;
      } catch { /* VoiceFullscreen not available yet (Subagent C) */ }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (speech.transcript) setInput(speech.transcript);
  }, [speech.transcript]);

  useEffect(() => {
    if (speech.interimTranscript && !speech.transcript) setInput(speech.interimTranscript);
  }, [speech.interimTranscript, speech.transcript]);

  useEffect(() => {
    if (speech.error) setDictationError(speech.error);
  }, [speech.error]);

  useEffect(() => {
    const el = bottomRef.current;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback((e) => {
    e?.preventDefault?.();
    const text = input.trim();
    if (!text) return;
    if (onSend) {
      onSend(text);
    } else if (shell?.send) {
      setLocalMessages((prev) => [...prev, { id: newId(), role: 'user', text }]);
      shell.send({ type: 'chat_request', payload: { text } });
    }
    setInput('');
    if (speech.listening) speech.stop();
  }, [input, onSend, shell, speech]);

  const toggleDictation = useCallback(() => {
    if (speech.listening) {
      speech.stop();
    } else {
      setDictationError(null);
      speech.start();
    }
  }, [speech]);

  const handleMicPointerDown = useCallback(() => {
    longPressTriggeredRef.current = false;
    longPressTimerRef.current = setTimeout(() => {
      longPressTriggeredRef.current = true;
      if (speech.listening) speech.stop();
      setVoiceFullscreenOpen(true);
    }, LONG_PRESS_MS);
  }, [speech]);

  const handleMicPointerUp = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    if (!longPressTriggeredRef.current) toggleDictation();
  }, [toggleDictation]);

  const handleMicPointerLeave = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  }, []);

  const retryDictation = useCallback(() => {
    setDictationError(null);
    speech.reset();
    speech.start();
  }, [speech]);

  const VoiceFullscreen = VoiceFullscreenRef.current;

  return (
    <div className="phone-chat-panel" data-testid="phone-chat-panel">
      <div className="phone-chat-log" data-testid="chat-log">
        {messages.map((m) => (
          <div key={m.id} className={`phone-chat-row phone-chat-row--${m.role}`}>
            <div className="phone-chat-bubble">{m.text}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form className="phone-chat-composer" onSubmit={handleSend} data-testid="chat-composer">
        <div className="phone-chat-input-wrap">
          {speech.listening && (
            <span className="phone-chat-recording-dot" aria-hidden="true" data-testid="recording-dot" />
          )}
          <input
            className="phone-chat-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            data-testid="chat-input"
          />
        </div>

        <button
          type="button"
          className={`phone-chat-mic${speech.listening ? ' is-listening' : ''}${!speech.supported ? ' is-disabled' : ''}`}
          disabled={!speech.supported}
          onPointerDown={speech.supported ? handleMicPointerDown : undefined}
          onPointerUp={speech.supported ? handleMicPointerUp : undefined}
          onPointerLeave={speech.supported ? handleMicPointerLeave : undefined}
          aria-label="Dictate message"
          aria-pressed={speech.listening}
          title={!speech.supported ? 'Dictation not supported on this browser; long-press for voice mode' : undefined}
          data-testid="mic-button"
        >
          <Mic size={18} />
        </button>

        <button
          type="submit"
          className="phone-chat-send"
          disabled={!input.trim()}
          aria-label="Send"
          data-testid="send-button"
        >
          <Send size={18} />
        </button>
      </form>

      {dictationError && (
        <div className="phone-chat-error" role="alert" data-testid="dictation-error">
          <span>{dictationError.message}</span>
          <button type="button" onClick={retryDictation} data-testid="retry-link">
            Retry
          </button>
        </div>
      )}

      {voiceFullscreenOpen && VoiceFullscreen && (
        <VoiceFullscreen
          open={voiceFullscreenOpen}
          onClose={() => setVoiceFullscreenOpen(false)}
          initialMode="listening"
        />
      )}
    </div>
  );
}
