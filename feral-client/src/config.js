const explicitBase = (import.meta.env.VITE_BRAIN_BASE_URL || '').trim();

let apiBase = explicitBase.replace(/\/$/, '');
if (!apiBase) {
  const host = import.meta.env.VITE_BRAIN_HOST || window.location.hostname || 'localhost';
  const port = import.meta.env.VITE_BRAIN_PORT || window.location.port || '9090';
  const scheme = window.location.protocol === 'https:' ? 'https' : 'http';
  const origin = `${host}${port ? `:${port}` : ''}`;
  apiBase = `${scheme}://${origin}`;
}

const wsBase = apiBase.startsWith('https://')
  ? apiBase.replace(/^https:\/\//, 'wss://')
  : apiBase.replace(/^http:\/\//, 'ws://');

export const API_BASE = apiBase;
export const WS_BASE = wsBase;
export const WS_URL = `${wsBase}/v1/session`;
