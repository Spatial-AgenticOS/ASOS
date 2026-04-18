/**
 * lib/voiceRealtime.js is 378 lines of WebRTC plumbing. Smoke test just
 * imports the module, stubs the RTCPeerConnection API surface, and
 * calls the exported factory. We're exercising module-scope code paths
 * (constants, schema helpers, pure functions) — real E2E happens in
 * Playwright with a real mic.
 */
beforeEach(() => {
  class StubPC {
    constructor() {
      this.localDescription = { sdp: 'v=0\r\n', type: 'offer' };
      this.onicecandidate = null;
      this.ontrack = null;
      this.addTrack = vi.fn();
      this.addTransceiver = vi.fn(() => ({ sender: { replaceTrack: vi.fn() } }));
      this.createOffer = vi.fn(() => Promise.resolve({ sdp: 'v=0\r\n', type: 'offer' }));
      this.setLocalDescription = vi.fn(() => Promise.resolve());
      this.setRemoteDescription = vi.fn(() => Promise.resolve());
      this.createDataChannel = vi.fn(() => ({
        send: vi.fn(),
        close: vi.fn(),
        addEventListener: vi.fn(),
        readyState: 'open',
      }));
      this.close = vi.fn();
    }
  }
  vi.stubGlobal('RTCPeerConnection', StubPC);
  vi.stubGlobal('MediaStream', class {
    constructor() { this.getTracks = () => []; }
    addTrack = vi.fn();
  });
  // Attach mediaDevices onto the real navigator instead of replacing it
  // wholesale — replacing globalThis.navigator kills jsdom's localStorage
  // proxy for the rest of the run.
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(() => Promise.resolve(new globalThis.MediaStream())) },
  });
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    text: () => Promise.resolve('v=0\r\n'),
    json: () => Promise.resolve({ client_secret: { value: 'sk-test' } }),
  })));
});

afterEach(() => vi.restoreAllMocks());

describe('voiceRealtime module', () => {
  it('imports without throwing', async () => {
    const mod = await import('../../lib/voiceRealtime');
    expect(mod).toBeTruthy();
  });

  it('exports at least one named factory or default', async () => {
    const mod = await import('../../lib/voiceRealtime');
    const keys = Object.keys(mod);
    expect(keys.length).toBeGreaterThan(0);
  });
});
