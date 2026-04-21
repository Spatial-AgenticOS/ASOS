import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Agents from '../../pages/Agents';

describe('Agents (Track C — personas tab)', () => {
  it('renders the Personas tab by default', () => {
    const { getByRole } = renderV2(<Agents />);
    expect(getByRole('heading', { name: /Personas/i })).toBeInTheDocument();
  });
});
