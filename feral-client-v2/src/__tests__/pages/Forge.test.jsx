import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Forge from '../../pages/Forge';

describe('Forge', () => {
  it('renders the Tool Genesis pane', () => {
    const { getByRole } = renderV2(<Forge />);
    expect(getByRole('heading', { name: /Forge/i })).toBeInTheDocument();
  });
});
