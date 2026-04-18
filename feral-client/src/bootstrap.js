/**
 * Bootstrap the browser client with a FERAL API key on first load.
 *
 * The brain auto-generates ``~/.feral/api_key`` on first boot. When the user
 * opens ``http://localhost:9090`` in a browser we hit the loopback-only
 * ``/api/auth/local-key`` endpoint to seed ``localStorage.feral_api_key``
 * so WebSocket + REST calls (Glass Brain, Settings, dashboard) authenticate
 * correctly even when ``FERAL_LOCAL_BYPASS`` is disabled.
 *
 * If the endpoint fails (e.g. remote client, key missing) we fail silently —
 * the existing UI will display its own visible-error banner and the user can
 * paste the key manually in Settings.
 */
export async function bootstrapLocalApiKey() {
  try {
    if (typeof window === 'undefined' || typeof localStorage === 'undefined') return;
    if (localStorage.getItem('feral_api_key')) return;
    const scheme = window.location.protocol === 'https:' ? 'https' : 'http';
    const host = window.location.hostname || 'localhost';
    const port = window.location.port || '9090';
    const url = `${scheme}://${host}:${port}/api/auth/local-key`;
    const r = await fetch(url, { credentials: 'same-origin' });
    if (!r.ok) return;
    const data = await r.json();
    if (data && data.api_key) {
      localStorage.setItem('feral_api_key', data.api_key);
    }
  } catch (_e) {
    // Silent — UI has its own visible-error banner for downstream failures.
  }
}
