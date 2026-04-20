import React from 'react';

/**
 * StatusDot — small colored dot with optional pulsing animation. Tone maps
 * to one of the semantic state tokens; never invents a color.
 */
const TONE_CLASS = {
  live: 'v2-dot--live',
  warn: 'v2-dot--warn',
  error: 'v2-dot--error',
  neutral: 'v2-dot--neutral',
  off: 'v2-dot--off',
};

export default function StatusDot({ tone = 'neutral', pulse = false, label }) {
  const toneClass = TONE_CLASS[tone] || TONE_CLASS.neutral;
  return (
    <span
      className={`v2-dot ${toneClass}${pulse ? ' is-pulse' : ''}`}
      role={label ? 'status' : 'presentation'}
      aria-label={label}
    />
  );
}
