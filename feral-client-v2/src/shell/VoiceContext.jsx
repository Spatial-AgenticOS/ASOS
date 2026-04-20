import React, { createContext, useContext } from 'react';
import { useVoiceMode } from '../hooks/useVoiceMode';

const VoiceContext = createContext(null);

export function VoiceProvider({ children }) {
  const value = useVoiceMode();
  return (
    <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>
  );
}

export function useVoice() {
  const ctx = useContext(VoiceContext);
  if (!ctx) {
    // Allow use outside the provider in tests — return an inert snapshot.
    return {
      state: 'off',
      provider: null,
      transcript: '',
      active: false,
      setProvider: () => {},
      start: () => {},
      stop: () => {},
      toggle: () => {},
    };
  }
  return ctx;
}
