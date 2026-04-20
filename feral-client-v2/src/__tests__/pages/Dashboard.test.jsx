import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Dashboard from '../../pages/Dashboard';

describe('Dashboard (now re-exports Home)', () => {
  it('is now the merged Home page', () => {
    const { container } = renderV2(<Dashboard />);
    expect(container.querySelector('.v2-home-hero-body')).toBeTruthy();
  });
});
