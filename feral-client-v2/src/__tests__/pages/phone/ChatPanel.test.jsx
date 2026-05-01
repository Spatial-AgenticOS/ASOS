import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, act, waitFor } from '@testing-library/react';
import ChatPanel from '../../../pages/phone/ChatPanel';

let mockSpeechState;
const mockStart = vi.fn();
const mockStop = vi.fn();
const mockReset = vi.fn();

vi.mock('../../../hooks/useWebSpeech', () => ({
  useWebSpeech: () => mockSpeechState,
  default: () => mockSpeechState,
}));

vi.mock('../../../pages/phone/VoiceFullscreen', () => ({
  VoiceFullscreen: ({ open, onClose, initialMode }) => (
    open ? <div data-testid="voice-fullscreen" data-mode={initialMode}>
      <button onClick={onClose} data-testid="vf-close">Close</button>
    </div> : null
  ),
  default: ({ open, onClose, initialMode }) => (
    open ? <div data-testid="voice-fullscreen" data-mode={initialMode}>
      <button onClick={onClose} data-testid="vf-close">Close</button>
    </div> : null
  ),
}));

function defaultSpeechState(overrides = {}) {
  return {
    supported: true, listening: false, transcript: '', interimTranscript: '',
    start: mockStart, stop: mockStop, reset: mockReset, error: null,
    ...overrides,
  };
}

describe('ChatPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockSpeechState = defaultSpeechState();
    mockStart.mockClear();
    mockStop.mockClear();
    mockReset.mockClear();
  });

  afterEach(() => { vi.useRealTimers(); });

  it('renders the chat log and input field', () => {
    const { getByTestId } = render(<ChatPanel />);
    expect(getByTestId('chat-log')).toBeTruthy();
    expect(getByTestId('chat-input')).toBeTruthy();
    expect(getByTestId('mic-button')).toBeTruthy();
    expect(getByTestId('send-button')).toBeTruthy();
  });

  it('renders default greeting message', () => {
    const { getByText } = render(<ChatPanel />);
    expect(getByText('Ask anything to the paired brain.')).toBeTruthy();
  });

  it('mic button has correct aria attributes', () => {
    const { getByTestId } = render(<ChatPanel />);
    const mic = getByTestId('mic-button');
    expect(mic.getAttribute('aria-label')).toBe('Dictate message');
    expect(mic.getAttribute('aria-pressed')).toBe('false');
  });

  it('short-tap mic toggles dictation — starts listening', () => {
    const { getByTestId } = render(<ChatPanel />);
    const mic = getByTestId('mic-button');
    fireEvent.pointerDown(mic);
    act(() => { vi.advanceTimersByTime(100); });
    fireEvent.pointerUp(mic);
    expect(mockStart).toHaveBeenCalled();
  });

  it('short-tap mic when already listening calls stop', () => {
    mockSpeechState = defaultSpeechState({ listening: true });
    const { getByTestId } = render(<ChatPanel />);
    const mic = getByTestId('mic-button');
    fireEvent.pointerDown(mic);
    act(() => { vi.advanceTimersByTime(100); });
    fireEvent.pointerUp(mic);
    expect(mockStop).toHaveBeenCalled();
  });

  it('dictation updates input field as transcript arrives', () => {
    mockSpeechState = defaultSpeechState({ transcript: 'hello world' });
    const { getByTestId } = render(<ChatPanel />);
    expect(getByTestId('chat-input').value).toBe('hello world');
  });

  it('interim transcript shows in input when no final transcript', () => {
    mockSpeechState = defaultSpeechState({ interimTranscript: 'hel' });
    const { getByTestId } = render(<ChatPanel />);
    expect(getByTestId('chat-input').value).toBe('hel');
  });

  it('long-press (400ms+) opens VoiceFullscreen and starts voice session', async () => {
    const shell = {
      deviceId: 'device-1',
      voice_config: { mode: 'openai_realtime' },
      sendFrame: vi.fn(),
      subscribeFrame: vi.fn(() => () => {}),
      node: {
        startMic: vi.fn(async () => {}),
        stopMic: vi.fn(async () => {}),
      },
    };
    const { getByTestId, queryByTestId } = render(<ChatPanel shell={shell} />);
    expect(queryByTestId('voice-fullscreen')).toBeNull();
    const mic = getByTestId('mic-button');
    fireEvent.pointerDown(mic);
    act(() => { vi.advanceTimersByTime(450); });
    fireEvent.pointerUp(mic);
    await act(async () => { await Promise.resolve(); });
    expect(queryByTestId('voice-fullscreen')).toBeTruthy();
    expect(shell.sendFrame).toHaveBeenCalledWith(
      'voice_session_start',
      expect.objectContaining({
        voice_mode: 'openai_realtime',
        sample_rate: 24000,
      }),
    );
    expect(shell.node.startMic).toHaveBeenCalled();
    expect(getByTestId('voice-fullscreen').getAttribute('data-mode')).toBe('listening');
  });

  it('unsupported browser renders disabled mic button', () => {
    mockSpeechState = defaultSpeechState({ supported: false });
    const { getByTestId } = render(<ChatPanel />);
    const mic = getByTestId('mic-button');
    expect(mic.disabled).toBe(true);
    expect(mic.getAttribute('title')).toContain('not supported');
  });

  it('recording dot appears when listening', () => {
    mockSpeechState = defaultSpeechState({ listening: true });
    const { getByTestId } = render(<ChatPanel />);
    expect(getByTestId('recording-dot')).toBeTruthy();
  });

  it('error state shows dictation error with retry link', () => {
    mockSpeechState = defaultSpeechState({
      error: { code: 'not-allowed', message: 'Microphone permission denied.' },
    });
    const { getByTestId, getByText } = render(<ChatPanel />);
    expect(getByTestId('dictation-error')).toBeTruthy();
    expect(getByText('Microphone permission denied.')).toBeTruthy();
    expect(getByTestId('retry-link')).toBeTruthy();
  });

  it('retry link calls reset and start', () => {
    mockSpeechState = defaultSpeechState({
      error: { code: 'not-allowed', message: 'Microphone permission denied.' },
    });
    const { getByTestId } = render(<ChatPanel />);
    fireEvent.click(getByTestId('retry-link'));
    expect(mockReset).toHaveBeenCalled();
    expect(mockStart).toHaveBeenCalled();
  });

  it('sends message via shell.sendFrame on form submit', () => {
    const shell = {
      deviceId: 'device-1',
      sendFrame: vi.fn(),
      subscribeFrame: vi.fn(() => () => {}),
    };
    const { getByTestId } = render(<ChatPanel shell={shell} />);
    fireEvent.change(getByTestId('chat-input'), { target: { value: 'test message' } });
    fireEvent.submit(getByTestId('chat-composer'));
    expect(shell.sendFrame).toHaveBeenCalledWith(
      'chat_request',
      expect.objectContaining({
        text: 'test message',
        reply_mode: 'stream',
        channel: 'chat',
      }),
    );
  });

  it('clears input after sending', () => {
    const shell = {
      deviceId: 'device-1',
      sendFrame: vi.fn(),
      subscribeFrame: vi.fn(() => () => {}),
    };
    const { getByTestId } = render(<ChatPanel shell={shell} />);
    const input = getByTestId('chat-input');
    fireEvent.change(input, { target: { value: 'clear me' } });
    fireEvent.submit(getByTestId('chat-composer'));
    expect(input.value).toBe('');
  });

  it('appends assistant reply from chat_response frame', async () => {
    let frameListener = null;
    const shell = {
      sendFrame: vi.fn(),
      subscribeFrame: vi.fn((cb) => {
        frameListener = cb;
        return () => {};
      }),
    };
    const { queryByText } = render(<ChatPanel shell={shell} />);
    act(() => {
      frameListener?.({
        type: 'chat_response',
        payload: { text: 'Assistant reply' },
      });
    });
    expect(queryByText('Assistant reply')).toBeTruthy();
  });
});
