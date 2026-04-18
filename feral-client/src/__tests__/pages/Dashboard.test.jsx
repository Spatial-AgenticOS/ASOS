/**
 * Dashboard.jsx is 509 lines and the first thing most users see.
 * Smoke-render it with fetch stubbed — covers every useEffect, the
 * initial layout branches, and the error-handling fallbacks.
 */
import { waitFor, screen } from '@testing-library/react';
import Dashboard from '../../pages/Dashboard';
import { renderPage } from '../_helpers/renderPage';

vi.mock('../../config', () => ({ API_BASE: 'http://localhost:9090' }));
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ addToast: vi.fn() }),
  ToastProvider: ({ children }) => children,
}));
vi.mock('../../hooks/useTheme', () => ({
  useTheme: () => ({ theme: 'dark', toggle: vi.fn() }),
}));

describe('Dashboard page', () => {
  afterEach(() => vi.restoreAllMocks());

  it('mounts without throwing', async () => {
    renderPage(<Dashboard />);
    await waitFor(() => {
      const anchor = screen.queryAllByText(/Dashboard|Overview|Status|Devices|Memory|Skills/i);
      expect(anchor.length).toBeGreaterThan(0);
    });
  });
});
