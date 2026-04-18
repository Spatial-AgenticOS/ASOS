import { waitFor, screen } from '@testing-library/react';
import TaskFlows from '../../pages/TaskFlows';
import { renderPage } from '../_helpers/renderPage';

vi.mock('../../config', () => ({ API_BASE: 'http://localhost:9090' }));
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ addToast: vi.fn() }),
  ToastProvider: ({ children }) => children,
}));

describe('TaskFlows page', () => {
  afterEach(() => vi.restoreAllMocks());

  it('mounts without throwing', async () => {
    renderPage(<TaskFlows />);
    await waitFor(() => {
      const anchor = screen.queryAllByText(/Flow|Task|Run|Routine|Scheduled/i);
      expect(anchor.length).toBeGreaterThan(0);
    });
  });
});
