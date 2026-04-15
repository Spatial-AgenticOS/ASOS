import React, { useMemo } from 'react';

const BAR_COUNT = 5;

export default function VoiceWaveform({ mode = 'idle' }) {
  const bars = useMemo(() => Array.from({ length: BAR_COUNT }, (_, i) => i), []);

  if (mode === 'idle') return null;

  if (mode === 'reconnecting') {
    return (
      <div className="flex items-center justify-center gap-2 h-8">
        <span className="w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-amber-400 animate-pulse">Reconnecting voice...</span>
      </div>
    );
  }

  if (mode === 'degraded') {
    return (
      <div className="flex items-center justify-center gap-2 h-8">
        <span className="text-xs text-rose-400">Voice unavailable — use text input</span>
      </div>
    );
  }

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
        <span className="voice-pulse-ring bg-feral-accent/30" />
      </div>
    );
  }

  if (mode === 'speaking') {
    return (
      <div className="flex items-center justify-center gap-[3px] h-8">
        {bars.map((i) => (
          <span
            key={i}
            className="voice-bar voice-bar-speak bg-feral-accent"
            style={{ animationDelay: `${i * 80}ms` }}
          />
        ))}
      </div>
    );
  }

  return null;
}
