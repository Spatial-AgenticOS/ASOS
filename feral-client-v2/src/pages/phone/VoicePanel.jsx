/**
 * VoicePanel — the "Voice" tab content on the phone.
 *
 * Shows a prominent "Start voice" button that opens VoiceFullscreen,
 * plus a scrollable session transcript history below.
 *
 * Consumes the shell context from a parent provider (same pattern as
 * ChatPanel / SettingsPanel). The shell must expose:
 *   - shell.send(type, payload)
 *   - shell.onFrame(cb) → unsubscribe fn
 *   - shell.voice_config  (optional, for mode display)
 *   - shell.node           (optional, BrowserNode instance)
 */
import { useState, useCallback } from 'react';
import { VoiceFullscreen } from './VoiceFullscreen';

export default function VoicePanel({ shell }) {
  const [fullscreenOpen, setFullscreenOpen] = useState(false);
  const [history, setHistory] = useState([]);

  const handleOpen = useCallback(() => {
    setFullscreenOpen(true);
    if (shell?.send) {
      shell.send('voice_session_start', {
        mode: shell?.voice_config?.mode || 'openai_realtime',
      });
    }
  }, [shell]);

  const handleClose = useCallback(() => {
    setFullscreenOpen(false);
  }, []);

  return (
    <div data-testid="voice-panel" style={{ padding: 16, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <button
        data-testid="start-voice-button"
        onClick={handleOpen}
        style={{
          width: '100%',
          padding: '18px 0',
          fontSize: 17,
          fontWeight: 600,
          color: '#fff',
          background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
          border: 'none',
          borderRadius: 14,
          cursor: 'pointer',
          marginBottom: 20,
        }}
      >
        Start voice
      </button>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {history.length === 0 && (
          <p style={{ textAlign: 'center', opacity: 0.4, fontSize: 14 }}>
            No voice sessions yet
          </p>
        )}
        {history.map((entry, i) => (
          <div
            key={i}
            style={{
              padding: '8px 0',
              borderBottom: '1px solid rgba(255,255,255,0.06)',
              fontSize: 14,
            }}
          >
            <span style={{ opacity: 0.5, marginRight: 8 }}>{entry.role === 'user' ? 'You' : 'Brain'}:</span>
            {entry.text}
          </div>
        ))}
      </div>

      <VoiceFullscreen
        open={fullscreenOpen}
        onClose={handleClose}
        initialMode="listening"
        shell={shell}
      />
    </div>
  );
}
