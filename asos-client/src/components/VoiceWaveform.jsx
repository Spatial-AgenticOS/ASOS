import React, { useMemo } from 'react';

const BAR_COUNT = 5;

export default function VoiceWaveform({ mode = 'idle' }) {
  const bars = useMemo(() => Array.from({ length: BAR_COUNT }, (_, i) => i), []);

  if (mode === 'idle') return null;

  if (mode === 'listening') {
    return (
      <div className="flex items-center justify-center gap-[3px] h-8">
        {bars.map((i) => (
          <span
            key={i}
            className="voice-bar voice-bar-listen bg-emerald-400"
            style={{ animationDelay: `${i * 120}ms` }}
          />
        ))}
      </div>
    );
  }

  if (mode === 'thinking') {
    return (
      <div className="flex items-center justify-center h-8">
        <span className="voice-pulse-ring bg-asos-accent/30" />
      </div>
    );
  }

  if (mode === 'speaking') {
    return (
      <div className="flex items-center justify-center gap-[3px] h-8">
        {bars.map((i) => (
          <span
            key={i}
            className="voice-bar voice-bar-speak bg-asos-accent"
            style={{ animationDelay: `${i * 80}ms` }}
          />
        ))}
      </div>
    );
  }

  return null;
}
