import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Settings from '../../pages/Settings';

describe('Settings', () => {
  it('renders the settings split layout with all sections', () => {
    const { getByRole, getByText } = renderV2(<Settings />);
    // Default section header = "General" (current section in the Pane title)
    expect(getByRole('heading', { name: /General/i })).toBeInTheDocument();
    for (const s of ['Providers', 'Memory', 'Channels', 'Autonomy', 'Voice']) {
      expect(getByText(s)).toBeInTheDocument();
    }
  });
});
