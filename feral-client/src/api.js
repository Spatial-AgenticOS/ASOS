import { API_BASE } from './config';

function authHeaders() {
  const key = typeof localStorage !== 'undefined' ? localStorage.getItem('feral_api_key') : '';
  const h = { 'Content-Type': 'application/json' };
  if (key) {
    h.Authorization = `Bearer ${key}`;
  }
  return h;
}

/**
 * Same-origin fetch with Bearer token from localStorage when present.
 * @param {string} path - Path starting with /api/... or absolute URL
 * @param {RequestInit} [init]
 */
export function apiFetch(path, init = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
  const next = {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init.headers || {}),
    },
  };
  return fetch(url, next);
}

export async function ensureClientApiKey() {
  try {
    const r = await apiFetch('/api/session/client-key');
    if (!r.ok) return;
    const j = await r.json();
    if (j.key && typeof localStorage !== 'undefined') {
      localStorage.setItem('feral_api_key', j.key);
    }
  } catch {
    /* offline */
  }
}
