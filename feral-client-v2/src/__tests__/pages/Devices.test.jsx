import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Devices from '../../pages/Devices';

describe('Devices', () => {
  it('renders the HUP Node pane', () => {
    const { getByRole } = renderV2(<Devices />);
    expect(getByRole('heading', { name: /Devices/i })).toBeInTheDocument();
  });
});
