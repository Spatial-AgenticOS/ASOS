import React from 'react';
import { Outlet } from 'react-router-dom';
import Ambient from './Ambient';
import Menubar from './Menubar';
import Dock from './Dock';
import { VoiceProvider, useVoice } from './VoiceContext';
import VoiceOverlay from './VoiceOverlay';
import PerceptionShare from '../components/PerceptionShare';

/**
 * Shell is the v2 chrome: ambient background + minimal top menubar + bottom
 * dock. Pages render in the Outlet between them. The VoiceProvider lifts
 * voice state so Menubar + VoiceOverlay agree on one mode.
 *
 * PerceptionShare.FloatingChip is mounted at the Shell level so the
 * "Sharing camera" indicator is visible no matter which route the user
 * navigates to after they grant permission.
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
      <PerceptionShare.FloatingChip />
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
