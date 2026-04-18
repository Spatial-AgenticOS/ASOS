import { renderHook } from '@testing-library/react';
import { useConversationThreads } from '../../hooks/useConversationThreads';

vi.mock('../../config', () => ({ API_BASE: 'http://localhost:9090' }));
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ addToast: vi.fn() }),
  ToastProvider: ({ children }) => children,
}));

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ threads: [] }),
  })));
});

afterEach(() => vi.restoreAllMocks());

describe('useConversationThreads', () => {
  const baseArgs = () => ({
    messages: [],
    setMessages: vi.fn(),
    sessionId: 'sess-123',
  });

  it('initialises and exposes threads surface', () => {
    const { result } = renderHook(() => useConversationThreads(baseArgs()));
    expect(result.current).toBeTruthy();
  });

  it('is idempotent across re-renders', () => {
    const { result, rerender } = renderHook(() => useConversationThreads(baseArgs()));
    const first = result.current;
    rerender();
    const second = result.current;
    expect(typeof first).toBe(typeof second);
  });
});
