import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Ambient from '../../pages/Ambient';

describe('Ambient (now re-exports Home)', () => {
  it('renders the merged Home surface', () => {
    const { container } = renderV2(<Ambient />);
    expect(container.querySelector('.v2-home-hero-body')).toBeTruthy();
  });
});
