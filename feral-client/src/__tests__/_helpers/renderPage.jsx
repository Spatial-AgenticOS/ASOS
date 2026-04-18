/**
 * Shared helpers for page-level smoke tests.
 *
 * Pages touch a lot of ambient surface — fetch, WebSocket, window.location,
 * lucide-react icons, useToast, useTheme, react-router. The helper below
 * stubs all of it so individual page tests can stay short and focused on
 * "does this render without throwing?"
 */
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * Default happy-path fetch response body. Individual tests can override by
 * calling ``installFetchMock(customResponder)`` before rendering.
 */
export const DEFAULT_FETCH_BODY = {
  ok: true,
  status: 'ok',
  version: '2026.4.13',
  items: [],
  results: [],
  skills: [],
  devices: [],
  sessions: [],
  memories: [],
  events: [],
  routines: [],
  pending: [],
  installed: [],
  channels: {},
  status_by_channel: {},
  providers: [],
  models: [],
  total: 0,
  timeline: [],
  intents: [],
  taskflows: [],
  // Common nested shapes referenced by the Dashboard/Ambient/etc pages.
  data: {},
  config: {},
  identity: {},
  metrics: {},
};

/**
 * Install a global fetch stub that returns ``DEFAULT_FETCH_BODY`` as JSON
 * for every request. Use ``installFetchMock(url => customBody)`` to route
 * specific URLs to specific responses.
 */
export function installFetchMock(responder) {
  const resolveBody = typeof responder === 'function'
    ? responder
    : () => DEFAULT_FETCH_BODY;

  vi.stubGlobal(
    'fetch',
    vi.fn((input, init) => {
      const url = typeof input === 'string' ? input : input?.url || '';
      const body = resolveBody(url, init) ?? DEFAULT_FETCH_BODY;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
        headers: new Map(),
      });
    }),
  );
}

/** Minimal WebSocket stub — pages that open one don't crash. */
export class StubWebSocket {
  constructor() {
    this.readyState = 1;
    this.send = vi.fn();
    this.close = vi.fn();
    this.addEventListener = vi.fn();
    this.removeEventListener = vi.fn();
    // Fire onopen asynchronously so any useEffect that waits on it completes.
    setTimeout(() => this.onopen?.({}), 0);
  }
}

/** Install a router-wrapped, fetch-mocked, websocket-stubbed DOM. */
export function renderPage(ui, { route = '/' } = {}) {
  installFetchMock();
  vi.stubGlobal('WebSocket', StubWebSocket);
  // Ensure window.matchMedia exists (some components call it during mount).
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockImplementation(q => ({
      matches: false,
      media: q,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  }
  // Ensure IntersectionObserver exists (lazy-loaders use it).
  if (!global.IntersectionObserver) {
    global.IntersectionObserver = class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
      takeRecords = vi.fn(() => []);
    };
  }
  // Ensure ResizeObserver exists (charts + responsive panels use it).
  if (!global.ResizeObserver) {
    global.ResizeObserver = class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    };
  }
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);
}
