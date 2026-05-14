/**
 * Theme — programmatic access to the v2 design tokens.
 *
 * Components that compute inline styles or need token values in JS
 * read from this module instead of hardcoding CSS var strings.
 * This is the JS twin of tokens.css; every value maps 1:1.
 *
 * For purely CSS-driven styling, use var(--v2-*) directly in .css files.
 */

export const theme = Object.freeze({
  color: {
    bgBase: 'var(--v2-bg-base)',
    bgDeep: 'var(--v2-bg-deep)',
    surface0: 'var(--v2-surface-0)',
    surface1: 'var(--v2-surface-1)',
    surface2: 'var(--v2-surface-2)',
    surfaceElev: 'var(--v2-surface-elev)',
    hairline: 'var(--v2-hairline)',
    hairlineStrong: 'var(--v2-hairline-strong)',
    hairlineFocus: 'var(--v2-hairline-focus)',
    textPrimary: 'var(--v2-text-primary)',
    textSecondary: 'var(--v2-text-secondary)',
    textTertiary: 'var(--v2-text-tertiary)',
    textInverse: 'var(--v2-text-inverse)',
    accent: 'var(--v2-accent)',
    accentSoft: 'var(--v2-accent-soft)',
    accentRing: 'var(--v2-accent-ring)',
    stateLive: 'var(--v2-state-live)',
    stateLiveSoft: 'var(--v2-state-live-soft)',
    stateWarn: 'var(--v2-state-warn)',
    stateWarnSoft: 'var(--v2-state-warn-soft)',
    stateError: 'var(--v2-state-error)',
    stateErrorSoft: 'var(--v2-state-error-soft)',
  },
  blur: {
    sm: 'var(--v2-blur-sm)',
    md: 'var(--v2-blur-md)',
    lg: 'var(--v2-blur-lg)',
  },
  radius: {
    xs: 'var(--v2-radius-xs)',
    sm: 'var(--v2-radius-sm)',
    md: 'var(--v2-radius-md)',
    lg: 'var(--v2-radius-lg)',
    pill: 'var(--v2-radius-pill)',
  },
  font: {
    system: 'var(--v2-font-system)',
    mono: 'var(--v2-font-mono)',
  },
  size: {
    xs: 'var(--v2-size-xs)',
    sm: 'var(--v2-size-sm)',
    base: 'var(--v2-size-base)',
    md: 'var(--v2-size-md)',
    lg: 'var(--v2-size-lg)',
    xl: 'var(--v2-size-xl)',
    xxl: 'var(--v2-size-2xl)',
  },
  motion: {
    easeOut: 'var(--v2-ease-out)',
    easeIn: 'var(--v2-ease-in)',
    durFast: 'var(--v2-dur-fast)',
    durBase: 'var(--v2-dur-base)',
    durSlow: 'var(--v2-dur-slow)',
  },
  shadow: {
    glass: 'var(--v2-shadow-glass)',
    glassSoft: 'var(--v2-shadow-glass-soft)',
    focus: 'var(--v2-shadow-focus)',
  },

  // Glass level semantics — locks the vocabulary for the Glass component.
  glass: {
    level0: { surface: 'var(--v2-surface-0)', blur: 'var(--v2-blur-sm)' },
    level1: { surface: 'var(--v2-surface-1)', blur: 'var(--v2-blur-md)' },
    level2: { surface: 'var(--v2-surface-2)', blur: 'var(--v2-blur-lg)' },
    elev: { surface: 'var(--v2-surface-elev)', blur: 'var(--v2-blur-lg)' },
  },
});

export default theme;
