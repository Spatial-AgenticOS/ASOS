import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Marketplace from '../../pages/Marketplace';

describe('Marketplace', () => {
  it('renders all 9 kind segments including app', () => {
    const { getByText, getByRole } = renderV2(<Marketplace />);
    expect(getByRole('heading', { name: /Marketplace/i })).toBeInTheDocument();
    for (const k of ['skill', 'app', 'daemon', 'mcp', 'channel', 'provider', 'memory', 'workflow', 'agent']) {
      expect(getByText(k)).toBeInTheDocument();
    }
  });
});
