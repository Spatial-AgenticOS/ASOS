import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AppShell from '../components/AppShell';

beforeEach(() => {
  // AppShell's useEffect hits /health on mount to pick up the live
  // version. Stub fetch so the effect resolves with a known calver.
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({ version: '2026.4.13' }),
      }),
    ),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

vi.mock('../hooks/useTheme', () => ({
  useTheme: () => ({ theme: 'dark', toggle: vi.fn() }),
}));
vi.mock('../components/TheOrb', () => ({
  default: () => <span data-testid="orb" />,
}));

function renderShell() {
  return render(
    <MemoryRouter>
      <AppShell />
    </MemoryRouter>,
  );
}

describe('AppShell', () => {
  it('renders FERAL branding', () => {
    renderShell();
    expect(screen.getByText('FERAL')).toBeInTheDocument();
    expect(screen.getByText('Unleashed AI')).toBeInTheDocument();
  });

  it('renders navigation items', () => {
    renderShell();
    const links = screen.getAllByText('Dashboard');
    expect(links.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Chat').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Settings').length).toBeGreaterThanOrEqual(1);
  });

  it('renders a calver version number after the health probe', async () => {
    renderShell();
    // AppShell starts with ``v...`` then asyncs-in the real version from
    // /health; waitFor handles both code paths.
    await waitFor(() => {
      const all = screen.getAllByText(/^v\d{4}\.\d{1,2}\.\d{1,2}$/);
      expect(all.length).toBeGreaterThanOrEqual(1);
    });
  });
});
