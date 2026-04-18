import { renderHook } from '@testing-library/react';
import { useWikiPanel } from '../../hooks/useWikiPanel';

vi.mock('../../config', () => ({ API_BASE: 'http://localhost:9090' }));

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ entries: [], pages: [] }),
  })));
});

afterEach(() => vi.restoreAllMocks());

describe('useWikiPanel', () => {
  it('initialises without throwing', () => {
    const { result } = renderHook(() => useWikiPanel());
    expect(result.current).toBeTruthy();
  });
});
