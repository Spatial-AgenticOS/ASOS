import React from 'react';

/**
 * Orb — the persona anchor. One entity, one state machine. Used in chat,
 * voice, ambient, and wherever FERAL needs to show "it".
 *
 * Modes: idle | listening | thinking | speaking | alerting | observing.
 */
const MODE_CLASS = {
  idle: 'v2-orb--idle',
  listening: 'v2-orb--listening',
  thinking: 'v2-orb--thinking',
  speaking: 'v2-orb--speaking',
  alerting: 'v2-orb--alerting',
  observing: 'v2-orb--observing',
  offline: 'v2-orb--offline',
};

export default function Orb({ size = 120, mode = 'idle', label = 'FERAL', className = '' }) {
  const cls = MODE_CLASS[mode] || MODE_CLASS.idle;
  return (
    <div
      className={`v2-orb ${cls} ${className}`.trim()}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${label} · ${mode}`}
      data-mode={mode}
    >
      <div className="v2-orb-core" />
      <div className="v2-orb-ring" />
      <div className="v2-orb-halo" />
    </div>
  );
}
