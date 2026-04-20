import React from 'react';
import Orb from '../ui/Orb';
import Glass from '../ui/Glass';
import { useVoice } from './VoiceContext';

const PROVIDER_LABEL = {
  openai: 'OpenAI Realtime',
  gemini: 'Gemini Live',
  'local-whisper': 'Local Whisper + Piper',
};

/**
 * VoiceOverlay — the mode transition. When voice is active, the overlay
 * dims the foreground, centers the Orb, shows a live transcript strip,
 * and names the provider so the user is never misled about what's
 * driving their voice.
 */
export default function VoiceOverlay() {
  const voice = useVoice();
  const visible = voice.active;
  const mode =
    voice.state === 'starting' ? 'thinking' :
    voice.state === 'reconnecting' ? 'thinking' :
    voice.state === 'degraded' ? 'alerting' :
    voice.state === 'active' ? 'speaking' :
    'idle';

  return (
    <div
      className={`v2-voice-overlay${visible ? ' is-visible' : ''}`}
      aria-hidden={!visible}
      role="dialog"
      aria-label="Voice session"
    >
      <div className="v2-voice-orb">
        <Orb size={320} mode={mode} label="FERAL voice" />
      </div>
      <div className="v2-voice-meta">
        <Glass level={2} radius="pill" padding="sm" className="v2-voice-provider">
          <span className="v2-voice-dot" />
          {PROVIDER_LABEL[voice.provider] || voice.provider || 'Voice'}
        </Glass>
        <div className="v2-voice-status">
          {voice.state === 'starting' && 'Opening channel…'}
          {voice.state === 'active' && 'Listening — speak naturally.'}
          {voice.state === 'reconnecting' && 'Reconnecting…'}
          {voice.state === 'degraded' && 'Brain socket down — voice paused.'}
        </div>
      </div>
      {voice.transcript && (
        <Glass level={1} radius="md" padding="md" className="v2-voice-transcript">
          <span>{voice.transcript}</span>
        </Glass>
      )}
      <Glass level={2} radius="pill" padding="sm" className="v2-voice-endbar">
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
