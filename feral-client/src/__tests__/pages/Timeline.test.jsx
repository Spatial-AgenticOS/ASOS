import { waitFor, screen } from '@testing-library/react';
import Timeline from '../../pages/Timeline';
import { renderPage } from '../_helpers/renderPage';

vi.mock('../../config', () => ({ API_BASE: 'http://localhost:9090' }));
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ addToast: vi.fn() }),
  ToastProvider: ({ children }) => children,
}));
vi.mock('../../hooks/useTheme', () => ({
  useTheme: () => ({ theme: 'dark', toggle: vi.fn() }),
}));

describe('Timeline page', () => {
  afterEach(() => vi.restoreAllMocks());

  it('mounts without throwing', async () => {
    renderPage(<Timeline />);
    await waitFor(() => {
      const anchor = screen.queryAllByText(/Timeline|Events|Activity|Today|History/i);
      expect(anchor.length).toBeGreaterThan(0);
    });
  });
});
