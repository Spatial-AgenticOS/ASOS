/**
 * Thin fetch wrapper. All v2 REST calls go through apiFetch so we have a
 * single chokepoint to add auth headers, handle 401s, and surface errors.
 */
import { API_BASE } from './config';

function readApiKey() {
  try {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem('feral_api_key');
  } catch {
    return null;
  }
}

export async function apiFetch(path, init = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const headers = new Headers(init.headers || {});
  const key = readApiKey();
  if (key && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${key}`);
  }
  if (init.body && !headers.has('Content-Type') && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(url, { ...init, headers, credentials: 'same-origin' });
  return response;
}

export async function apiJson(path, init = {}) {
  const r = await apiFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText || 'request failed';
    try {
      const body = await r.clone().json();
      if (typeof body?.detail === 'string' && body.detail.trim()) {
        detail = body.detail.trim();
      } else if (body?.detail && typeof body.detail === 'object') {
        detail = typeof body.detail.message === 'string'
          ? body.detail.message
          : JSON.stringify(body.detail);
      } else if (typeof body?.error === 'string' && body.error.trim()) {
        detail = body.error.trim();
      }
    } catch {
      const text = await r.text().catch(() => '');
      if (text.trim()) detail = text.trim();
    }
    throw new Error(`${r.status} ${detail} @ ${path}`);
  }
  return r.json();
}
