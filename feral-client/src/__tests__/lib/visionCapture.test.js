/**
 * lib/visionCapture.js is the vision-frame extraction helper (80 lines).
 * Smoke-import + stubbed MediaStreamTrack/ImageCapture to cover the
 * module-level branches.
 */
beforeEach(() => {
  vi.stubGlobal('ImageCapture', class {
    grabFrame = vi.fn(() => Promise.resolve({ width: 10, height: 10 }));
    takePhoto = vi.fn(() => Promise.resolve(new Blob([''], { type: 'image/jpeg' })));
  });
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn(() => Promise.resolve({
        getVideoTracks: () => [{ stop: vi.fn() }],
        getTracks: () => [],
      })),
    },
  });
});

afterEach(() => vi.restoreAllMocks());

describe('visionCapture module', () => {
  it('imports without throwing', async () => {
    const mod = await import('../../lib/visionCapture');
    expect(mod).toBeTruthy();
  });
});
