/**
 * BrowserNode handshake tests — proves the HUP envelope leaving the
 * browser is exactly what the Brain's /v1/node WebSocket handler expects.
 *
 * Uses a mock WebSocket so the test can assert on every frame sent.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    MockWebSocket.instances.push(this);
    // Open asynchronously so connect() awaits onopen.
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.();
    }, 0);
  }
  send(data) { this.sent.push(data); }
  close() { this.readyState = MockWebSocket.CLOSED; this.onclose?.(); }
}
MockWebSocket.instances = [];

describe('BrowserNode', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => ({}) })));

    const storage = {};
    vi.stubGlobal('localStorage', {
      getItem: (k) => (k in storage ? storage[k] : null),
      setItem: (k, v) => { storage[k] = v; },
    });

    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/605',
      geolocation: { watchPosition: () => 1, clearWatch: () => {} },
      mediaDevices: {},
      vibrate: () => true,
    });
    // Don't stub window — jsdom's window is read-only but already matches.
    if (typeof window !== 'undefined') {
      Object.defineProperty(window, 'location', {
        value: { origin: 'http://brain.local:9090' },
        writable: true,
        configurable: true,
      });
    }
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('builds ws url with token + platform + declares node_type browser_node', async () => {
    const { BrowserNode } = await import('../node/BrowserNode.js');
    const node = new BrowserNode({ token: 'abc123', name: 'Test Phone' });

    expect(node.wsUrl).toBe('ws://brain.local:9090/v1/node?api_key=abc123');
    expect(node.platform).toBe('ios-browser');
    expect(node.capabilities).toContain('location');
    expect(node.capabilities).toContain('display');
  });

  it('sends node_register on connect and calls /api/devices/pair/complete', async () => {
    const { BrowserNode } = await import('../node/BrowserNode.js');
    const phases = [];
    const node = new BrowserNode({
      token: 'TOKEN1',
      name: 'My Phone',
      onPhase: (p) => phases.push(p),
    });

    await node.connect();

    expect(MockWebSocket.instances).toHaveLength(1);
    const ws = MockWebSocket.instances[0];
    expect(ws.sent).toHaveLength(1);
    const frame = JSON.parse(ws.sent[0]);
    expect(frame.type).toBe('node_register');
    expect(frame.hup_version).toBe('1.0');
    expect(frame.payload.node_type).toBe('browser_node');
    expect(frame.payload.name).toBe('My Phone');
    expect(frame.payload.capabilities).toContain('location');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/devices/pair/complete'),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('TOKEN1'),
      }),
    );

    expect(phases).toContain('connected');
    expect(phases).toContain('registered');
  });

  it('rejects construction with no token', async () => {
    const { BrowserNode } = await import('../node/BrowserNode.js');
    expect(() => new BrowserNode({})).toThrow(/token/i);
  });
});
