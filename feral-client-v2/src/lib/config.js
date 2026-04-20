/**
 * Brain API/WS endpoints for feral-client-v2.
 *
 * Mirrors feral-client/src/config.js exactly so v1 and v2 hit the same Brain
 * when served from the same origin. Keeping this as a local copy (rather than
 * importing from sibling v1) avoids cross-package imports and keeps each
 * client independently buildable.
 */

const rawBase = (import.meta.env.VITE_BRAIN_BASE_URL || '').trim();

let apiBase = rawBase.replace(/\/$/, '');
if (!apiBase) {
  const host =
    import.meta.env.VITE_BRAIN_HOST ||
    (typeof window !== 'undefined' && window.location.hostname) ||
    'localhost';
  const port =
    import.meta.env.VITE_BRAIN_PORT ||
    (typeof window !== 'undefined' && window.location.port) ||
    '9090';
  const scheme =
    typeof window !== 'undefined' && window.location.protocol === 'https:'
      ? 'https'
      : 'http';
  const origin = `${host}${port ? `:${port}` : ''}`;
  apiBase = `${scheme}://${origin}`;
}

const wsBase = apiBase.startsWith('https://')
  ? apiBase.replace(/^https:\/\//, 'wss://')
  : apiBase.replace(/^http:\/\//, 'ws://');

export const API_BASE = apiBase;
export const WS_BASE = wsBase;
export const WS_URL = `${wsBase}/v1/session`;
