import React from 'react';
import { Mic, MicOff, Sun, Moon } from 'lucide-react';
import { useConnectionStatus } from '../hooks/useConnectionStatus';
import { useTheme } from '../hooks/useTheme';
import { useVoice } from './VoiceContext';

/**
 * Top menubar — minimal. Left: FERAL mark + connection state. Right: voice
 * toggle. Command palette + identity slot in later.
 */
export default function Menubar() {
  const { state } = useConnectionStatus();
  const voice = useVoice();
  const { theme, toggle: toggleTheme } = useTheme();

  const statusColor =
    state === 'open' ? 'var(--v2-state-live)' :
    state === 'connecting' ? 'var(--v2-state-warn)' :
    state === 'error' ? 'var(--v2-state-error)' :
    'var(--v2-text-tertiary)';

  const voiceLabel = voice.active ? 'End voice session' : 'Start voice session';

  return (
    <header className="v2-menubar" role="banner">
      <div className="v2-menubar-left">
        <span className="v2-menubar-dot" style={{ background: statusColor }} aria-hidden="true" />
        <span className="v2-menubar-brand">FERAL</span>
        <span className="v2-menubar-version">v2</span>
      </div>
      <div className="v2-menubar-right" aria-label="Menubar actions">
        <button
          type="button"
          className="v2-menubar-theme"
          onClick={toggleTheme}
          aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          title={theme === 'light' ? 'Switch to dark' : 'Switch to light'}
        >
          {theme === 'light' ? <Sun size={14} /> : <Moon size={14} />}
        </button>
        <button
          type="button"
          className={`v2-menubar-voice${voice.active ? ' is-active' : ''}`}
          onClick={() => voice.toggle()}
          aria-pressed={voice.active}
          aria-label={voiceLabel}
          title={voiceLabel}
          disabled={state !== 'open' && !voice.active}
        >
          {voice.active ? <Mic size={15} /> : <MicOff size={15} />}
          <span className="v2-menubar-voice-label">
            {voice.active ? 'Listening' : 'Voice'}
          </span>
        </button>
      </div>
    </header>
  );
}
