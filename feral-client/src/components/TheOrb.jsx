import React from 'react';

/**
 * The Orb -- FERAL's visual identity.
 *
 * Props:
 *   size     — px diameter (default 32)
 *   mode     — 'idle' | 'listening' | 'thinking' | 'speaking' | 'alert' | 'disconnected'
 *   connected — boolean. SHOWS the tiny emerald status dot; the
 *               default is `false` (Phase-1 truthfulness sweep) so a
 *               caller that forgets to pass a real signal does NOT
 *               render an unbound green dot. Every existing call
 *               site passes a bound expression; new callers must do
 *               the same.
 */
export default function TheOrb({ size = 32, mode = 'idle', connected = false }) {
  const modeClass =
    mode === 'listening'    ? 'orb-listening' :
    mode === 'thinking'     ? 'orb-thinking' :
    mode === 'speaking'     ? 'orb-speaking' :
    mode === 'alert'        ? 'orb-alert' :
    mode === 'disconnected' ? 'orb-disconnected' :
    'orb-idle';

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <div
        className={`orb ${modeClass}`}
        style={{ width: size, height: size }}
      />
      {connected && mode !== 'disconnected' && (
        <span
          className="absolute bg-emerald-400 rounded-full"
          style={{
            width: Math.max(4, size * 0.18),
            height: Math.max(4, size * 0.18),
            top: size * 0.05,
            right: size * 0.05,
            boxShadow: '0 0 4px rgba(52,211,153,0.7)',
          }}
        />
      )}
    </div>
  );
}
