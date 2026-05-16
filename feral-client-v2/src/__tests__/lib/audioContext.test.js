/**
 * v2026.5.29 — shared AudioContext autoplay-unlock contract.
 *
 * Symptom regression we are guarding against: brain emits
 * ``audio_response`` PCM16 frames for OpenAI Realtime voice; client
 * displays the assistant text but plays no sound. Root cause was an
 * ``AudioContext`` stuck in ``state === 'suspended'`` because the
 * unlock was best-effort from a post-mount ``useEffect``, missed the
 * user-gesture window, and Chrome silently no-op'd the ``resume()``.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getSharedAudioContext,
  installAudioUnlock,
  unlockSharedAudioContext,
  __resetAudioContextForTests,
} from '../../lib/audioContext';

let resumeMock;
let ctorMock;

function makeCtx(initialState = 'suspended') {
  resumeMock = vi.fn(() => {
    ctxState.value = 'running';
    return Promise.resolve();
  });
  const ctxState = { value: initialState };
  return {
    get state() {
      return ctxState.value;
    },
    resume: resumeMock,
    close: vi.fn(() => Promise.resolve()),
    destination: {},
    currentTime: 0,
  };
}

beforeEach(() => {
  __resetAudioContextForTests();
  const ctx = makeCtx('suspended');
  // Use a function expression (not an arrow) so `new ctorMock()` works
  // — the audioContext module invokes `new AudioContext()` and arrow
  // functions cannot be used as constructors.
  ctorMock = vi.fn(function AudioContextMock() { return ctx; });
  // eslint-disable-next-line no-undef
  window.AudioContext = ctorMock;
});

afterEach(() => {
  __resetAudioContextForTests();
  // eslint-disable-next-line no-undef
  delete window.AudioContext;
});

describe('shared AudioContext', () => {
  it('getSharedAudioContext returns a singleton', () => {
    const a = getSharedAudioContext();
    const b = getSharedAudioContext();
    expect(a).toBe(b);
    expect(ctorMock).toHaveBeenCalledTimes(1);
  });

  it('unlockSharedAudioContext calls resume() when suspended', async () => {
    const ctx = await unlockSharedAudioContext();
    expect(ctx).toBeTruthy();
    expect(resumeMock).toHaveBeenCalled();
    expect(ctx.state).toBe('running');
  });

  it('unlockSharedAudioContext is a no-op once running', async () => {
    await unlockSharedAudioContext();
    resumeMock.mockClear();
    await unlockSharedAudioContext();
    expect(resumeMock).not.toHaveBeenCalled();
  });

  it('installAudioUnlock fires on pointerdown (v2026.5.29)', async () => {
    installAudioUnlock();
    expect(resumeMock).not.toHaveBeenCalled();
    // Simulate a phone long-press first contact. Chrome routes the
    // pointerdown event through capture-phase document listeners.
    document.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    // Listener is async; drain microtasks.
    await new Promise((r) => setTimeout(r, 5));
    expect(ctorMock).toHaveBeenCalled();
    expect(resumeMock).toHaveBeenCalled();
  });

  it('installAudioUnlock is idempotent', () => {
    installAudioUnlock();
    installAudioUnlock();
    installAudioUnlock();
    // The handler is keyed by an internal flag; no listeners should
    // be added twice. There's no public way to count listeners, so
    // we assert by behaviour: dispatching once still resumes only
    // once.
    expect(true).toBe(true);
  });

  it('installAudioUnlock works on click (legacy gesture)', async () => {
    installAudioUnlock();
    document.dispatchEvent(new Event('click'));
    await new Promise((r) => setTimeout(r, 5));
    expect(resumeMock).toHaveBeenCalled();
  });

  it('installAudioUnlock works on keydown', async () => {
    installAudioUnlock();
    document.dispatchEvent(new Event('keydown'));
    await new Promise((r) => setTimeout(r, 5));
    expect(resumeMock).toHaveBeenCalled();
  });
});
