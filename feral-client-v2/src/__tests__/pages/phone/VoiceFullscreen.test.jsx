import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, act } from '@testing-library/react';
import { VoiceFullscreen } from '../../../pages/phone/VoiceFullscreen';

let frameListeners = [];

function makeShell(overrides = {}) {
  return {
    send: vi.fn(),
    onFrame: vi.fn((cb) => {
      frameListeners.push(cb);
      return () => {
        frameListeners = frameListeners.filter((l) => l !== cb);
      };
    }),
    voice_config: { mode: 'openai_realtime' },
    node: null,
    ...overrides,
  };
}

function pushFrame(type, payload = {}) {
  act(() => {
    frameListeners.forEach((cb) => cb({ type, payload }));
  });
}

beforeEach(() => {
  frameListeners = [];

  vi.stubGlobal('requestAnimationFrame', vi.fn((cb) => setTimeout(cb, 0)));
  vi.stubGlobal('cancelAnimationFrame', vi.fn((id) => clearTimeout(id)));

  const mockStream = {
    getTracks: () => [{ stop: vi.fn() }],
  };
  vi.stubGlobal('navigator', {
    ...navigator,
    vibrate: vi.fn(() => true),
    mediaDevices: {
      getUserMedia: vi.fn(() => Promise.resolve(mockStream)),
    },
  });

  vi.stubGlobal('AudioContext', vi.fn(() => ({
    createMediaStreamSource: vi.fn(() => ({
      connect: vi.fn(),
    })),
    createAnalyser: vi.fn(() => ({
      fftSize: 256,
      frequencyBinCount: 128,
      getByteFrequencyData: vi.fn((arr) => arr.fill(0)),
      connect: vi.fn(),
    })),
    close: vi.fn(() => Promise.resolve()),
  })));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  frameListeners = [];
});

describe('VoiceFullscreen', () => {
  it('does not render when open=false', () => {
    const { queryByTestId } = render(
      <VoiceFullscreen open={false} onClose={vi.fn()} shell={makeShell()} />,
    );
    expect(queryByTestId('voice-fullscreen')).toBeNull();
  });

  it('renders the dialog when open=true', () => {
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={makeShell()} />,
    );
    const dialog = getByTestId('voice-fullscreen');
    expect(dialog).toBeInTheDocument();
    expect(dialog.getAttribute('role')).toBe('dialog');
    expect(dialog.getAttribute('aria-label')).toBe('Voice agent');
  });

  it('shows provider badge for openai_realtime', () => {
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={makeShell()} />,
    );
    expect(getByTestId('provider-badge').textContent).toBe('OpenAI Realtime');
  });

  it('shows provider badge for gemini_live', () => {
    const shell = makeShell({ voice_config: { mode: 'gemini_live' } });
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} />,
    );
    expect(getByTestId('provider-badge').textContent).toBe('Gemini Live');
  });

  it('shows provider badge for chained mode', () => {
    const shell = makeShell({ voice_config: { mode: 'chained' } });
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} />,
    );
    expect(getByTestId('provider-badge').textContent).toBe('Chained (Deepgram)');
  });

  it('close button sends voice_interrupt and calls onClose', () => {
    const onClose = vi.fn();
    const shell = makeShell();
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={onClose} shell={shell} />,
    );

    fireEvent.click(getByTestId('close-button'));
    expect(shell.send).toHaveBeenCalledWith('voice_interrupt', {});
    expect(onClose).toHaveBeenCalled();
  });

  it('mute button toggles and sends voice_mute envelope', () => {
    const shell = makeShell();
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} />,
    );

    const muteBtn = getByTestId('mute-button');
    expect(muteBtn.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(muteBtn);
    expect(shell.send).toHaveBeenCalledWith('voice_mute', { muted: true });
    expect(muteBtn.getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(muteBtn);
    expect(shell.send).toHaveBeenCalledWith('voice_mute', { muted: false });
  });

  it('keyboard button calls onClose', () => {
    const onClose = vi.fn();
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={onClose} shell={makeShell()} />,
    );

    fireEvent.click(getByTestId('keyboard-button'));
    expect(onClose).toHaveBeenCalled();
  });

  it('Escape key closes the dialog', () => {
    const onClose = vi.fn();
    const shell = makeShell();
    render(<VoiceFullscreen open={true} onClose={onClose} shell={shell} />);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('voice_state frame transitions state machine', () => {
    const shell = makeShell();
    const { queryByText } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} initialMode="idle" />,
    );

    pushFrame('voice_state', { state: 'listening' });
    pushFrame('voice_state', { state: 'processing' });
    expect(queryByText('Brain is thinking…')).toBeInTheDocument();
  });

  it('transcript frame shows partial and final text', () => {
    const shell = makeShell();
    const { getByTestId, queryByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} />,
    );

    pushFrame('transcript', { text: 'hello wor', is_final: false });
    expect(getByTestId('partial-transcript').textContent).toBe('hello wor');

    pushFrame('transcript', { text: 'hello world', is_final: true });
    expect(getByTestId('final-transcript').textContent).toBe('hello world');
    expect(queryByTestId('partial-transcript')).toBeNull();
  });

  it('error state shows error surface with retry button', () => {
    const shell = makeShell();
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} initialMode="idle" />,
    );

    pushFrame('voice_state', { state: 'error', message: 'Mic denied' });
    expect(getByTestId('error-surface')).toBeInTheDocument();
    expect(getByTestId('error-surface').textContent).toContain('Mic denied');
    expect(getByTestId('retry-button')).toBeInTheDocument();
  });

  it('retry button resets error state and sends voice_session_start', () => {
    const shell = makeShell();
    const { getByTestId, queryByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} />,
    );

    pushFrame('voice_state', { state: 'error', message: 'fail' });
    fireEvent.click(getByTestId('retry-button'));

    expect(shell.send).toHaveBeenCalledWith('voice_session_start', {});
    expect(queryByTestId('error-surface')).toBeNull();
  });

  it('tap on orb sends voice_interrupt when speaking', () => {
    const shell = makeShell();
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} />,
    );

    pushFrame('voice_state', { state: 'speaking' });
    fireEvent.click(getByTestId('orb-container'));
    expect(shell.send).toHaveBeenCalledWith('voice_interrupt', {});
  });

  it('tap on orb does NOT send interrupt when not speaking', () => {
    const shell = makeShell();
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} initialMode="idle" />,
    );

    fireEvent.click(getByTestId('orb-container'));
    expect(shell.send).not.toHaveBeenCalledWith('voice_interrupt', expect.anything());
  });

  it('haptics fire on listening→processing transition', () => {
    const shell = makeShell();
    render(<VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} initialMode="listening" />);

    pushFrame('voice_state', { state: 'processing' });
    expect(navigator.vibrate).toHaveBeenCalledWith(50);
  });

  it('haptics fire error pattern on error state', () => {
    const shell = makeShell();
    render(<VoiceFullscreen open={true} onClose={vi.fn()} shell={shell} initialMode="idle" />);

    pushFrame('voice_state', { state: 'error', message: 'fail' });
    expect(navigator.vibrate).toHaveBeenCalledWith([30, 30, 30]);
  });

  it('renders VoiceOrb canvas inside the orb container', () => {
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={makeShell()} />,
    );
    expect(getByTestId('voice-orb-canvas')).toBeInTheDocument();
  });

  it('has aria-modal and tabIndex for accessibility focus trap', () => {
    const { getByTestId } = render(
      <VoiceFullscreen open={true} onClose={vi.fn()} shell={makeShell()} />,
    );
    const dialog = getByTestId('voice-fullscreen');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.tabIndex).toBe(-1);
  });
});
