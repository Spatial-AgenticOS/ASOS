/**
 * Bootstrap the browser client with a FERAL API key on first load, and
 * redirect to the setup wizard when the Brain has not completed setup yet.
 *
 * The brain auto-generates ``~/.feral/api_key`` on first boot. When the user
 * opens ``http://localhost:9090/v2/`` we hit the loopback-only
 * ``/api/auth/local-key`` endpoint to seed ``localStorage.feral_api_key`` so
 * WebSocket + REST calls authenticate correctly.
 */
import { API_BASE } from './lib/config';

export async function bootstrapLocalApiKey() {
  try {
    if (typeof window === 'undefined' || typeof localStorage === 'undefined') return;
    if (localStorage.getItem('feral_api_key')) return;
    const r = await fetch(`${API_BASE}/api/auth/local-key`, { credentials: 'same-origin' });
    if (!r.ok) return;
    const data = await r.json();
    if (data && data.api_key) {
      localStorage.setItem('feral_api_key', data.api_key);
    }
  } catch (_e) {
    // Silent — downstream UI surfaces its own errors.
  }
}

/**
 * Redirect to /v2/setup when ``setup_complete === false`` and we aren't
 * already there. Idempotent; resolves before the SPA mounts so new users
 * never see a broken dashboard on first boot.
 */
export async function maybeRedirectToSetup() {
  try {
    if (typeof window === 'undefined') return;
    if (window.location.pathname.startsWith('/v2/setup')) return;
    const r = await fetch(`${API_BASE}/api/setup/status`, { credentials: 'same-origin' });
    if (!r.ok) return;
    const data = await r.json();
    if (data && data.setup_complete === false) {
      window.location.replace('/v2/setup');
    }
  } catch (_e) {
    // Silent.
  }
}
