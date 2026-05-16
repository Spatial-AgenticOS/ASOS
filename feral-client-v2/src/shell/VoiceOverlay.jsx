import React, { useState, useEffect } from 'react';
import Orb from '../ui/Orb';
import Glass from '../ui/Glass';
import { useVoice } from './VoiceContext';

const PROVIDER_LABEL = {
  openai: 'OpenAI Realtime',
  gemini: 'Gemini Live',
  'local-whisper': 'Local Whisper + Piper',
};

/**
 * VoiceOverlay — desktop voice surface.
 *
 * v2026.5.30 — voice no longer takes over the whole viewport by
 * default. Pre-fix the overlay was `position:fixed; inset:0;
 * pointer-events:auto` *and* `.v2-shell.is-voice-mode` dimmed the
 * main content to 0.4 brightness, so starting voice from the
 * menubar effectively locked the entire WebUI. The operator could
 * not keep typing in chat, switch tabs, or look at the dashboard.
 *
 * Now it renders as a compact docked strip pinned to the bottom-
 * right of the viewport with the orb, provider badge, status, mute
 * (when supported), expand, and end. An explicit Expand control
 * flips to the original full-viewport layout for screen-share /
 * presentation mode. Voice can be running and the chat / dock /
 * dashboard stay fully interactive.
 */
export default function VoiceOverlay() {
  const voice = useVoice();
  const visible = voice.active;
  const [variant, setVariant] = useState('docked'); // 'docked' | 'fullscreen'
  // Each time voice starts fresh, default back to docked so an
  // operator who expanded once doesn't keep getting the full takeover.
  useEffect(() => {
    if (!visible) setVariant('docked');
  }, [visible]);

  const mode =
    voice.state === 'starting' ? 'thinking' :
    voice.state === 'reconnecting' ? 'thinking' :
    voice.state === 'degraded' ? 'alerting' :
    voice.state === 'active' ? 'speaking' :
    'idle';

  const providerLabel = PROVIDER_LABEL[voice.provider] || voice.provider || 'Voice';
  const statusText =
    voice.state === 'starting' ? 'Opening channel…' :
    voice.state === 'active' ? 'Listening — speak naturally.' :
    voice.state === 'reconnecting' ? 'Reconnecting…' :
    voice.state === 'degraded' ? 'Brain socket down — voice paused.' :
    '';

  const isFullscreen = variant === 'fullscreen';

  return (
    <div
      className={
        `v2-voice-overlay v2-voice-overlay--${variant}` +
        (visible ? ' is-visible' : '')
      }
      data-variant={variant}
      aria-hidden={!visible}
      role={isFullscreen ? 'dialog' : 'region'}
      aria-modal={isFullscreen ? 'true' : undefined}
      aria-label="Voice session"
    >
      <div className="v2-voice-orb">
        <Orb
          size={isFullscreen ? 320 : 56}
          mode={mode}
          label="FERAL voice"
        />
      </div>
      <div className="v2-voice-meta">
        <Glass level={2} radius="pill" padding="sm" className="v2-voice-provider">
          <span className="v2-voice-dot" />
          {providerLabel}
        </Glass>
        {statusText && (
          <div className="v2-voice-status">{statusText}</div>
        )}
      </div>
      {voice.transcript && isFullscreen && (
        <Glass level={1} radius="md" padding="md" className="v2-voice-transcript">
          <span>{voice.transcript}</span>
        </Glass>
      )}
      <Glass level={2} radius="pill" padding="sm" className="v2-voice-endbar">
        <button
          type="button"
          className="v2-btn"
          aria-label={isFullscreen ? 'Minimize voice' : 'Expand voice'}
          onClick={() => setVariant(isFullscreen ? 'docked' : 'fullscreen')}
        >
          {isFullscreen ? 'Minimize' : 'Expand'}
        </button>
        <button
          type="button"
          className="v2-btn v2-btn--primary"
          onClick={() => voice.stop()}
        >
          End voice
        </button>
      </Glass>
    </div>
  );
}
