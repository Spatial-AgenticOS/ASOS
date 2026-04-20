import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import GlassBrain from '../../pages/GlassBrain';

describe('Glass Brain', () => {
  it('renders the event log pane', () => {
    const { getByRole } = renderV2(<GlassBrain />);
    expect(getByRole('heading', { name: /Glass Brain/i })).toBeInTheDocument();
  });
});
