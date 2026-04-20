import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import Orb from '../ui/Orb';
import Glass from '../ui/Glass';
import Pane from '../ui/Pane';

describe('v2 UI primitives', () => {
  it('Orb renders the requested mode as a data attribute', () => {
    const { container } = render(<Orb size={80} mode="thinking" />);
    const el = container.querySelector('.v2-orb');
    expect(el).toBeTruthy();
    expect(el.getAttribute('data-mode')).toBe('thinking');
  });

  it('Glass applies the chosen level + radius + pad classes', () => {
    const { container } = render(
      <Glass level={2} radius="lg" padding="sm">hi</Glass>,
    );
    const el = container.querySelector('.v2-glass');
    expect(el.className).toContain('v2-glass--level-2');
    expect(el.className).toContain('v2-glass--radius-lg');
    expect(el.className).toContain('v2-glass--pad-sm');
  });

  it('Pane renders the title in a heading', () => {
    const { getByRole } = render(<Pane title="Forge">children</Pane>);
    expect(getByRole('heading', { name: 'Forge' })).toBeInTheDocument();
  });
});
