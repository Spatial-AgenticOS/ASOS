/**
 * Shared helpers for v2 page + shell tests. Wraps components in a
 * MemoryRouter and stubs fetch + WebSocket so the shared FeralSocket + polling
 * hooks don't reach for a real network.
 */
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

export const DEFAULT_FETCH_BODY = {
  ok: true,
  status: 'ok',
  version: '2026.4.14',
  items: [],
  results: [],
  skills: [],
  devices: [],
  nodes: [],
  sessions: [],
  memories: [],
  events: [],
  routines: [],
  pending: [],
  installed: [],
  timeline: [],
  taskflows: [],
  intents: [],
  channels: {},
  providers: [],
  models: [],
  total: 0,
  data: {},
  config: {},
  identity: {},
  metrics: {},
  somatic: { cognitive_load: 0.2, heart_rate: 0 },
};

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
        statusText: 'OK',
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
        headers: new Map(),
      });
    }),
  );
}

export class StubWebSocket {
  constructor() {
    this.readyState = 1;
    this.send = vi.fn();
    this.close = vi.fn();
    this.addEventListener = vi.fn();
    this.removeEventListener = vi.fn();
    setTimeout(() => this.onopen?.({}), 0);
  }
}

export function renderV2(ui, { route = '/', fetch } = {}) {
  installFetchMock(fetch);
  vi.stubGlobal('WebSocket', StubWebSocket);
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockImplementation((q) => ({
      matches: false, media: q, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    }));
  }
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);
}
