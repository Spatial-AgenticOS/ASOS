import { describe, it, expect, afterEach, vi } from 'vitest';
import { act, cleanup, fireEvent } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Chat from '../../pages/Chat';

// PR2: when computer_use refuses a path, the brain emits a
// `permission_request` WS frame. The chat must render an inline
// approval card and forward the operator's decision back as a
// `ui_event` action_id of the form `perm_grant_<req_id>` /
// `perm_deny_<req_id>`. The previous client silently dropped the
// frame and the user only saw a stalled assistant turn.

const listeners = new Set();
const sendUiEventSpy = vi.fn();

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
    sendUiEvent: (...args) => sendUiEventSpy(...args),
  };
});

function emit(msg) {
  listeners.forEach((fn) => fn(msg));
}

afterEach(() => {
  listeners.clear();
  sendUiEventSpy.mockClear();
  cleanup();
});

describe('Chat — PR2 permission card', () => {
  it('renders an Allow / Deny card and forwards the perm_grant_<id> action', async () => {
    const { container } = renderV2(<Chat />);

    await act(async () => {
      emit({
        type: 'permission_request',
        payload: {
          request_id: 'req-abc',
          path: '/Users/me/Desktop',
          operation: 'write',
          reason: 'computer_use__write_file needs access to your Desktop folder.',
        },
      });
    });

    const card = container.querySelector('.v2-chat-perm');
    expect(card).toBeTruthy();
    const cardText = card.textContent;
    expect(cardText).toContain('FERAL needs permission to write to');
    expect(cardText).toContain('/Users/me/Desktop');
    expect(cardText).toContain('Desktop folder');

    const buttons = card.querySelectorAll('button');
    const allow = Array.from(buttons).find((b) => /allow/i.test(b.textContent));
    expect(allow).toBeTruthy();

    await act(async () => {
      fireEvent.click(allow);
    });

    expect(sendUiEventSpy).toHaveBeenCalledTimes(1);
    const [, payload] = sendUiEventSpy.mock.calls[0];
    expect(payload.action_id).toBe('perm_grant_req-abc');
    expect(payload.event).toBe('tap');

    // The live card collapses into a settled receipt so the user sees
    // their decision was registered.
    const after = container.querySelector('.v2-chat-perm--settled');
    expect(after).toBeTruthy();
    expect(after.textContent).toContain('Granted access');
  });

  it('Deny forwards perm_deny_<id> and shows a denial receipt', async () => {
    const { container } = renderV2(<Chat />);

    await act(async () => {
      emit({
        type: 'permission_request',
        payload: {
          request_id: 'req-zzz',
          path: '/Users/me/Desktop/secret',
          operation: 'read',
          reason: '',
        },
      });
    });

    const card = container.querySelector('.v2-chat-perm');
    const buttons = card.querySelectorAll('button');
    const deny = Array.from(buttons).find((b) => /deny/i.test(b.textContent));
    await act(async () => {
      fireEvent.click(deny);
    });

    const [, payload] = sendUiEventSpy.mock.calls[0];
    expect(payload.action_id).toBe('perm_deny_req-zzz');
    const settled = container.querySelector('.v2-chat-perm--settled');
    expect(settled.textContent).toContain('Denied access');
  });

  it('a re-emitted permission_request with the same id replaces (not duplicates) the card', async () => {
    const { container } = renderV2(<Chat />);

    await act(async () => {
      emit({
        type: 'permission_request',
        payload: { request_id: 'req-one', path: '/a', operation: 'write', reason: 'first' },
      });
      emit({
        type: 'permission_request',
        payload: { request_id: 'req-one', path: '/a', operation: 'write', reason: 'retry' },
      });
    });

    const cards = container.querySelectorAll('.v2-chat-perm');
    expect(cards.length).toBe(1);
    expect(cards[0].textContent).toContain('retry');
  });
});
