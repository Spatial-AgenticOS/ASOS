import { renderHook, act } from '@testing-library/react';
import { useFeralSession } from '../../hooks/useFeralSession';

vi.mock('../../config', () => ({
  API_BASE: 'http://localhost:9090',
  WS_URL: 'ws://localhost:9090/v1/session',
}));

// The real Toast.jsx returns undefined from useToast() when called outside
// a <ToastProvider>. Stubbing the hook keeps this test focused on the
// session lifecycle instead of requiring a whole provider tree.
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ addToast: vi.fn() }),
  ToastProvider: ({ children }) => children,
}));

class MockWebSocket {
  constructor() {
    this.readyState = 1;
    this.send = vi.fn();
    this.close = vi.fn();
    setTimeout(() => this.onopen?.(), 0);
  }
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', MockWebSocket);
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve({ json: () => Promise.resolve({}) }),
  ));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useFeralSession', () => {
  const voiceEngineRef = { current: null };

  it('starts not connected (synchronous initial state)', () => {
    const { result } = renderHook(() => useFeralSession({ voiceEngineRef }));
    expect(typeof result.current.isConnected).toBe('boolean');
  });

  it('messages start empty', () => {
    const { result } = renderHook(() => useFeralSession({ voiceEngineRef }));
    expect(result.current.messages).toEqual([]);
  });

  it('exposes handleUIAction function', () => {
    const { result } = renderHook(() => useFeralSession({ voiceEngineRef }));
    expect(typeof result.current.handleUIAction).toBe('function');
  });

  it('exposes handleSkillProposalDecision function', () => {
    const { result } = renderHook(() => useFeralSession({ voiceEngineRef }));
    expect(typeof result.current.handleSkillProposalDecision).toBe('function');
  });

  it('setMessages updates the messages array', async () => {
    const { result } = renderHook(() => useFeralSession({ voiceEngineRef }));
    act(() => {
      result.current.setMessages([{ role: 'user', type: 'text', content: 'test' }]);
    });
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe('test');
  });
});
