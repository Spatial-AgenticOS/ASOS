/**
 * Mirror of feral-core/genui/permissions_policy.py::build_csp_header.
 *
 * Derives the Content-Security-Policy that AppSurface bakes into its
 * sandboxed iframe srcdoc. Kept in step with the Python helper —
 * change one, change the other.
 *
 * Rules:
 *   - default-src 'none'
 *   - script-src 'unsafe-inline'   (the iframe's tiny bootstrap is inline)
 *   - style-src 'unsafe-inline'    (rendered SDUI styles are inline)
 *   - img-src/media-src/font-src   data: + https: (publishers' assets)
 *   - connect-src                  built from manifest.permissions.network
 *   - frame-ancestors 'self'       only the FERAL host page may embed
 *   - base-uri 'none', form-action 'none'
 *
 * Manifest permissions are accepted in two shapes:
 *   - legacy list of strings (`permissions: ["network:*", ...]`) — yields
 *     no network grant
 *   - dict-shape (`permissions: { network: [...], justification: "..." }`)
 */

const ORIGIN_RE = /^(?:https?:\/\/)?[a-zA-Z0-9.\-:*]+(?::\d+)?(?:\/.*)?$/;

function coerceCspSource(origin) {
  if (origin == null) return null;
  const o = String(origin).trim();
  if (!o) return null;
  if (o === '*') return '*';
  if (/^(https?|wss?):\/\//.test(o)) return o;
  if (ORIGIN_RE.test(o)) return `https://${o}`;
  return null;
}

export function networkAllowlist(manifest) {
  const perms = manifest?.permissions;
  if (perms == null) return [];
  if (Array.isArray(perms)) return [];
  if (typeof perms === 'object') {
    const net = perms.network;
    if (!Array.isArray(net)) return [];
    return net.map((x) => String(x));
  }
  return [];
}

export function buildCspHeader(manifest, { extraConnectSrc = [] } = {}) {
  const sources = [];
  const allow = networkAllowlist(manifest);
  for (const origin of allow) {
    const c = coerceCspSource(origin);
    if (c) sources.push(c);
  }
  for (const extra of extraConnectSrc) {
    const c = coerceCspSource(extra);
    if (c && !sources.includes(c)) sources.push(c);
  }

  const connect = sources.length === 0
    ? "connect-src 'none'"
    : `connect-src ${sources.join(' ')}`;

  return [
    "default-src 'none'",
    "script-src 'unsafe-inline'",
    "style-src 'unsafe-inline'",
    "img-src 'self' data: https:",
    "media-src 'self' data:",
    "font-src 'self' data:",
    connect,
    "frame-ancestors 'self'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join('; ');
}
