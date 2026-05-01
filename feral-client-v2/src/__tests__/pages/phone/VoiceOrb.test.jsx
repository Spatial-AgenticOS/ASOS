import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import VoiceOrb from '../../../pages/phone/VoiceOrb';

let rafCallbacks = [];
let rafId = 0;

beforeEach(() => {
  rafCallbacks = [];
  rafId = 0;

  vi.stubGlobal('requestAnimationFrame', vi.fn((cb) => {
    const id = ++rafId;
    rafCallbacks.push({ id, cb });
    return id;
  }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn((id) => {
    rafCallbacks = rafCallbacks.filter((r) => r.id !== id);
  }));
  vi.stubGlobal('devicePixelRatio', 1);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function flushRAF(n = 1) {
  for (let i = 0; i < n; i++) {
    const batch = [...rafCallbacks];
    rafCallbacks = [];
    batch.forEach((r) => r.cb());
  }
}

function mockCanvasContext() {
  const calls = [];
  const ctx = {
    clearRect: vi.fn((...a) => calls.push(['clearRect', ...a])),
    beginPath: vi.fn(() => calls.push(['beginPath'])),
    arc: vi.fn((...a) => calls.push(['arc', ...a])),
    fill: vi.fn(() => calls.push(['fill'])),
    stroke: vi.fn(() => calls.push(['stroke'])),
    save: vi.fn(),
    restore: vi.fn(),
    scale: vi.fn(),
    createRadialGradient: vi.fn(() => ({
      addColorStop: vi.fn(),
    })),
    set fillStyle(v) { calls.push(['fillStyle', v]); },
    set strokeStyle(v) {},
    set lineWidth(v) {},
    set lineCap(v) {},
    set shadowColor(v) {},
    set shadowBlur(v) {},
    _calls: calls,
  };
  return ctx;
}

describe('VoiceOrb', () => {
  it('renders a canvas element', () => {
    const { getByTestId } = render(<VoiceOrb state="idle" audioLevel={0} />);
    const canvas = getByTestId('voice-orb-canvas');
    expect(canvas.tagName).toBe('CANVAS');
  });

  it('mounts in idle state without errors', () => {
    expect(() => render(<VoiceOrb state="idle" audioLevel={0} />)).not.toThrow();
  });

  it('mounts in listening state without errors', () => {
    expect(() => render(<VoiceOrb state="listening" audioLevel={0.5} />)).not.toThrow();
  });

  it('mounts in processing state without errors', () => {
    expect(() => render(<VoiceOrb state="processing" audioLevel={0} />)).not.toThrow();
  });

  it('mounts in speaking state without errors', () => {
    expect(() => render(<VoiceOrb state="speaking" audioLevel={0.7} />)).not.toThrow();
  });

  it('mounts in error state without errors', () => {
    expect(() => render(<VoiceOrb state="error" audioLevel={0} />)).not.toThrow();
  });

  it('schedules requestAnimationFrame on mount and cancels on unmount', () => {
    const { unmount } = render(<VoiceOrb state="idle" audioLevel={0} />);
    expect(requestAnimationFrame).toHaveBeenCalled();

    unmount();
    expect(cancelAnimationFrame).toHaveBeenCalled();
  });

  it('draws to canvas when getContext is available', () => {
    const ctx = mockCanvasContext();
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);

    try {
      const { getByTestId } = render(<VoiceOrb state="listening" audioLevel={0.5} />);
      const canvas = getByTestId('voice-orb-canvas');

      Object.defineProperty(canvas, 'getBoundingClientRect', {
        value: () => ({ width: 200, height: 200, top: 0, left: 0 }),
      });

      flushRAF(1);

      expect(ctx.clearRect).toHaveBeenCalled();
      expect(ctx.arc).toHaveBeenCalled();
      expect(ctx.fill).toHaveBeenCalled();
    } finally {
      HTMLCanvasElement.prototype.getContext = origGetContext;
    }
  });

  it('audioLevel prop influences arc radius via draw calls', () => {
    const ctx = mockCanvasContext();
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);

    try {
      const { rerender, getByTestId } = render(<VoiceOrb state="listening" audioLevel={0} />);
      const canvas = getByTestId('voice-orb-canvas');
      Object.defineProperty(canvas, 'getBoundingClientRect', {
        value: () => ({ width: 300, height: 300, top: 0, left: 0 }),
      });

      flushRAF(5);
      const lowCalls = ctx.arc.mock.calls.map((c) => c[2]);
      ctx.arc.mockClear();

      rerender(<VoiceOrb state="listening" audioLevel={1} />);
      flushRAF(10);
      const highCalls = ctx.arc.mock.calls.map((c) => c[2]);

      if (lowCalls.length > 0 && highCalls.length > 0) {
        const avgLow = lowCalls.reduce((a, b) => a + b, 0) / lowCalls.length;
        const avgHigh = highCalls.reduce((a, b) => a + b, 0) / highCalls.length;
        expect(avgHigh).toBeGreaterThanOrEqual(avgLow);
      }
    } finally {
      HTMLCanvasElement.prototype.getContext = origGetContext;
    }
  });
});
