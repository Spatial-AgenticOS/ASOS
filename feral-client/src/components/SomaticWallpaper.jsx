import React from 'react';

/**
 * Full-screen somatic-state-driven radial gradient background.
 * Color maps to cognitive_load:
 *   0.0–0.4 → cyan  (calm)
 *   0.4–0.7 → amber (focused)
 *   0.7–1.0 → red   (stressed)
 * Pulse frequency syncs to heart rate when available.
 */
export default function SomaticWallpaper({ cognitiveLoad = 0, heartRate = 0 }) {
  let primary, secondary;
  if (cognitiveLoad > 0.7) {
    primary = 'rgba(239, 68, 68, 0.18)';
    secondary = 'rgba(239, 68, 68, 0.04)';
  } else if (cognitiveLoad > 0.4) {
    primary = 'rgba(245, 158, 11, 0.15)';
    secondary = 'rgba(245, 158, 11, 0.03)';
  } else {
    primary = 'rgba(6, 182, 212, 0.12)';
    secondary = 'rgba(6, 182, 212, 0.02)';
  }

  const pulseDuration = heartRate > 0 ? `${60 / heartRate}s` : '4s';

  return (
    <>
      <div
        aria-hidden
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 0,
          background: [
            `radial-gradient(ellipse at top, ${primary} 0%, ${secondary} 40%, transparent 70%)`,
            `radial-gradient(ellipse at bottom right, ${secondary} 0%, transparent 50%)`,
          ].join(', '),
          pointerEvents: 'none',
          transition: 'background 2s ease',
          animation: `somaticPulse ${pulseDuration} ease-in-out infinite`,
        }}
      />
      <style>{`
        @keyframes somaticPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
      `}</style>
    </>
  );
}
