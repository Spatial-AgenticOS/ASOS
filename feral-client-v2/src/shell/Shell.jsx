import React from 'react';
import { Outlet } from 'react-router-dom';
import Ambient from './Ambient';
import Menubar from './Menubar';
import Dock from './Dock';
import { VoiceProvider, useVoice } from './VoiceContext';
import VoiceOverlay from './VoiceOverlay';

/**
 * Shell is the v2 chrome: ambient background + minimal top menubar + bottom
 * dock. Pages render in the Outlet between them. The VoiceProvider lifts
 * voice state so Menubar + VoiceOverlay agree on one mode.
 */
function ShellFrame() {
  const voice = useVoice();
  return (
    <div className={`v2-shell${voice.active ? ' is-voice-mode' : ''}`}>
      <Ambient />
      <Menubar />
      <main className="v2-shell-main">
        <Outlet />
      </main>
      <Dock />
      <VoiceOverlay />
    </div>
  );
}

export default function Shell() {
  return (
    <VoiceProvider>
      <ShellFrame />
    </VoiceProvider>
  );
}
