import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AppShell from '../components/AppShell';

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

  it('renders version number', () => {
    renderShell();
    expect(screen.getByText('v1.2.0')).toBeInTheDocument();
  });

  it('renders TheOrb component', () => {
    renderShell();
    expect(screen.getAllByTestId('orb').length).toBeGreaterThanOrEqual(1);
  });
});
