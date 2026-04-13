import { render, screen, fireEvent } from '@testing-library/react';
import CommandPalette from '../components/CommandPalette';

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

const baseProps = {
  open: false,
  onClose: vi.fn(),
  onCommand: vi.fn(),
  onToggle: vi.fn(),
};

describe('CommandPalette', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<CommandPalette {...baseProps} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders palette when open', () => {
    render(<CommandPalette {...baseProps} open />);
    expect(screen.getByPlaceholderText('Search actions, pages, skills...')).toBeInTheDocument();
  });

  it('displays all default items', () => {
    render(<CommandPalette {...baseProps} open />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('filters items by search query', () => {
    render(<CommandPalette {...baseProps} open />);
    fireEvent.change(screen.getByPlaceholderText('Search actions, pages, skills...'), {
      target: { value: 'health' },
    });
    expect(screen.getByText('Check my health')).toBeInTheDocument();
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument();
  });

  it('calls onClose when backdrop is clicked', () => {
    const onClose = vi.fn();
    render(<CommandPalette {...baseProps} open onClose={onClose} />);
    fireEvent.click(document.querySelector('.palette-backdrop'));
    expect(onClose).toHaveBeenCalled();
  });
});
