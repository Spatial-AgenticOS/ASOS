import { waitFor, screen } from '@testing-library/react';
import Ambient from '../../pages/Ambient';
import { renderPage } from '../_helpers/renderPage';

vi.mock('../../config', () => ({ API_BASE: 'http://localhost:9090' }));
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ addToast: vi.fn() }),
  ToastProvider: ({ children }) => children,
}));

describe('Ambient page', () => {
  afterEach(() => vi.restoreAllMocks());

  it('mounts without throwing', async () => {
    renderPage(<Ambient />);
    await waitFor(() => {
      const anchor = screen.queryAllByText(/Ambient|Briefing|Desk|Wind|Mode|FERAL/i);
      expect(anchor.length).toBeGreaterThan(0);
    });
  });
});
