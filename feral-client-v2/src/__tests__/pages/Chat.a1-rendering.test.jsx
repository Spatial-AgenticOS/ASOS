import { describe, it, expect, afterEach } from 'vitest';
import { act, cleanup, fireEvent } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Chat, { sanitizeAssistantText } from '../../pages/Chat';

const listeners = new Set();

vi.mock('../../hooks/useFeralSocket', async () => {
  const fakeSocket = {
    state: 'open',
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    onState: (fn) => {
      try { fn('open'); } catch { /* test stub */ }
      return () => {};
    },
    send: vi.fn(),
  };
  return {
    useFeralSocket: () => fakeSocket,
    sendUiEvent: vi.fn(),
  };
});

function emit(msg) {
  listeners.forEach((fn) => fn(msg));
}

afterEach(() => {
  listeners.clear();
  cleanup();
});

describe('Chat — A1 rendering fixes', () => {
  it('sanitizer strips control tokens and tool-call tags', () => {
    expect(sanitizeAssistantText('hi<|eom|>')).toBe('hi');
    expect(sanitizeAssistantText('before</tool_calls>')).toBe('before');
    expect(sanitizeAssistantText('x <tool_calls>junk</tool_calls> y')).toBe('x  y');
    expect(sanitizeAssistantText('talking invoke[{"name":"q"}] done')).toContain('done');
    expect(sanitizeAssistantText('normal prose')).toBe('normal prose');
  });

  it('stream_delta residue never reaches the UI buffer', async () => {
    const { container } = renderV2(<Chat />);
    await act(async () => {
      emit({ type: 'stream_delta', payload: { delta: 'Hello<|eom|>', stream_id: 's1', is_final: false } });
    });
    const body = container.querySelectorAll('.v2-chat-body');
    const rendered = Array.from(body).map((n) => n.textContent).join(' ');
    expect(rendered).toContain('Hello');
    expect(rendered).not.toContain('<|eom|>');
  });

  it('tool_start renders a chip and tool_result clears it', async () => {
    const { container } = renderV2(<Chat />);
    // Put the UI into the thinking state the way a real submit would:
    // the chip row only renders under `thinking && !streamingText`.
    const input = container.querySelector('.v2-chat-input');
    const form = container.querySelector('form.v2-chat-composer');
    await act(async () => {
      fireEvent.change(input, { target: { value: 'go' } });
      fireEvent.submit(form);
    });

    await act(async () => {
      emit({ type: 'tool_start', payload: { tool: 'web_search__run', call_id: 'c1' } });
    });
    const texts = Array.from(container.querySelectorAll('.v2-chat-body'))
      .map((n) => n.textContent).join(' | ');
    expect(texts).toContain('using web_search__run');

    await act(async () => {
      emit({ type: 'tool_result', payload: { tool: 'web_search__run', call_id: 'c1', success: true } });
    });
    const after = Array.from(container.querySelectorAll('.v2-chat-body'))
      .map((n) => n.textContent).join(' | ');
    expect(after).not.toContain('using web_search__run');
  });
});
