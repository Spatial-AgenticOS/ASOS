import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Settings from '../../pages/Settings';

describe('Settings', () => {
  it('renders the settings split layout with all sections including Self', () => {
    const { getAllByText, getByText } = renderV2(<Settings />);
    // Default section is now "Self" — it appears both in the nav list
    // (as a button) and in the Pane title. getAllByText handles both.
    expect(getAllByText(/^Self$/i).length).toBeGreaterThan(0);
    for (const s of ['General', 'Providers', 'Memory', 'Channels', 'Autonomy', 'Voice']) {
      expect(getByText(s)).toBeInTheDocument();
    }
  });

  it('exposes a Self button in the settings nav that opens the Self editors', () => {
    const { getAllByText } = renderV2(<Settings />);
    // Self is in the left-nav AND rendered by default so it's present
    // immediately. The SelfWorkspace Pane title includes ABOUT-ME now.
    expect(getAllByText(/IDENTITY \/ SOUL \/ MEMORY \/ ABOUT-ME/i).length).toBeGreaterThan(0);
  });

  it('exposes an ABOUT ME tab inside the Self workspace', () => {
    const { getByRole } = renderV2(<Settings />);
    // Tabs renders each tab with role="tab"; ABOUT ME is the fourth
    // tab and must be clickable so the user can jump to /api/about-me
    // without leaving Settings.
    expect(getByRole('tab', { name: /ABOUT ME/i })).toBeInTheDocument();
  });
});
