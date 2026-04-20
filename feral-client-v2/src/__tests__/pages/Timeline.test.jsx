import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Timeline from '../../pages/Timeline';

describe('Timeline', () => {
  it('renders the Timeline pane', () => {
    const { getByRole } = renderV2(<Timeline />);
    expect(getByRole('heading', { name: /Timeline/i })).toBeInTheDocument();
  });
});
