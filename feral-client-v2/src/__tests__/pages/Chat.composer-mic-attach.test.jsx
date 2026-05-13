import { describe, it, expect, afterEach, vi } from 'vitest';
import { act, cleanup, fireEvent } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Chat from '../../pages/Chat';

// Gap-fill audit: Chat.jsx must expose a mic button AND a paperclip
// attach button inside the composer (Pane PR 9 + PR 10). These were
// missing from the previous slice and are required by the plan's
// "in-composer voice + attachments" line items.

const listeners = new Set();
const socketSend = vi.fn();
const voiceToggle = vi.fn();
const voiceStart = vi.fn();
const voiceStop = vi.fn();

vi.mock('../../hooks/useFeralSocket', async () => {
  const fakeSocket = {
    state: 'open',
    subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    onState: (fn) => { try { fn('open'); } catch { /* test stub */ } return () => {}; },
    send: (...a) => socketSend(...a),
  };
  return {
    useFeralSocket: () => fakeSocket,
    sendUiEvent: vi.fn(),
  };
});

vi.mock('../../shell/VoiceContext', () => ({
  useVoice: () => ({
    state: 'off',
    provider: 'openai',
    transcript: '',
    active: false,
    setProvider: vi.fn(),
    start: voiceStart,
    stop: voiceStop,
    toggle: voiceToggle,
  }),
}));

afterEach(() => {
  listeners.clear();
  socketSend.mockClear();
  voiceToggle.mockClear();
  voiceStart.mockClear();
  voiceStop.mockClear();
  cleanup();
});

describe('Chat composer (gap-fill PR 9 + PR 10)', () => {
  it('renders mic and paperclip buttons inside the composer', () => {
    const { container } = renderV2(<Chat />);
    const composer = container.querySelector('.v2-chat-composer');
    expect(composer).toBeTruthy();
    expect(composer.querySelector('.v2-chat-mic')).toBeTruthy();
    expect(composer.querySelector('.v2-chat-attach')).toBeTruthy();
  });

  it('mic button toggles the shared voice context', async () => {
    const { container } = renderV2(<Chat />);
    const mic = container.querySelector('.v2-chat-mic');
    await act(async () => fireEvent.click(mic));
    expect(voiceToggle).toHaveBeenCalledTimes(1);
  });

  it('paperclip opens the hidden file input', () => {
    const { container } = renderV2(<Chat />);
    const attach = container.querySelector('.v2-chat-attach');
    const fileInput = container.querySelector('input[type="file"]');
    expect(fileInput).toBeTruthy();
    const clickSpy = vi.spyOn(fileInput, 'click');
    fireEvent.click(attach);
    expect(clickSpy).toHaveBeenCalled();
  });

  it('text send works without attachments and omits the field on the wire', async () => {
    const { container } = renderV2(<Chat />);
    const input = container.querySelector('.v2-chat-input');
    await act(async () => {
      fireEvent.change(input, { target: { value: 'hello' } });
    });
    const form = container.querySelector('form.v2-chat-composer');
    await act(async () => { fireEvent.submit(form); });
    expect(socketSend).toHaveBeenCalledTimes(1);
    const payload = socketSend.mock.calls[0][0];
    expect(payload.type).toBe('text_command');
    expect(payload.payload.text).toBe('hello');
    // No attachments key when none are pending — keeps the WS shape
    // backward-compatible for older brain builds.
    expect(payload.payload.attachments).toBeUndefined();
  });
});
