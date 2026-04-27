/**
 * A4 — bootstrap must not hijack /pair.
 *
 * When the Brain has not finished setup (`setup_complete === false`),
 * `maybeRedirectToSetup` sends users to /setup. The device-pairing
 * landing page /pair?t=<token> runs before setup is guaranteed to be
 * complete (a phone can scan the QR on a fresh install) and the token
 * query must survive. Redirecting would both strip `?t=` and break the
 * pairing flow.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { maybeRedirectToSetup } from '../bootstrap';

function mockLocation(pathname, search = '') {
  const replace = vi.fn();
  const loc = {
    pathname,
    search,
    href: `http://localhost:9090${pathname}${search}`,
    replace,
  };
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: loc,
  });
  return replace;
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ setup_complete: false }),
  })));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('maybeRedirectToSetup', () => {
  it('does NOT redirect when on /pair even if setup is incomplete', async () => {
    const replace = mockLocation('/pair', '?t=deadbeefcafebabe');
    await maybeRedirectToSetup();
    expect(replace).not.toHaveBeenCalled();
  });

  it('does NOT redirect when on /v2/pair even if setup is incomplete', async () => {
    const replace = mockLocation('/v2/pair', '?t=abc123');
    await maybeRedirectToSetup();
    expect(replace).not.toHaveBeenCalled();
  });

  it('does NOT redirect when already on /setup', async () => {
    const replace = mockLocation('/setup');
    await maybeRedirectToSetup();
    expect(replace).not.toHaveBeenCalled();
  });

  it('DOES redirect to /setup from /dashboard when setup incomplete', async () => {
    const replace = mockLocation('/dashboard');
    await maybeRedirectToSetup();
    expect(replace).toHaveBeenCalledWith('/setup');
  });

  it('DOES redirect to /v2/setup from /v2/dashboard when setup incomplete', async () => {
    const replace = mockLocation('/v2/dashboard');
    await maybeRedirectToSetup();
    expect(replace).toHaveBeenCalledWith('/v2/setup');
  });

  it('does NOT redirect when setup_complete is true', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ setup_complete: true }),
    })));
    const replace = mockLocation('/dashboard');
    await maybeRedirectToSetup();
    expect(replace).not.toHaveBeenCalled();
  });
});
