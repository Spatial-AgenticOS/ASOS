import { renderHook } from '@testing-library/react';
import { useSessionSnapshots } from '../../hooks/useSessionSnapshots';

vi.mock('../../config', () => ({ API_BASE: 'http://localhost:9090' }));

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ snapshots: [] }),
  })));
});

afterEach(() => vi.restoreAllMocks());

describe('useSessionSnapshots', () => {
  it('initialises without throwing', () => {
    const { result } = renderHook(() => useSessionSnapshots('sess-123'));
    expect(result.current).toBeTruthy();
  });
});
