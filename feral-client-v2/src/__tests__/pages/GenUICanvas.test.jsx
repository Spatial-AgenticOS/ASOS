import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import GenUICanvas from '../../pages/GenUICanvas';

describe('GenUI Canvas', () => {
  it('renders the canvas pane + empty state', () => {
    const { getByRole, getByText } = renderV2(<GenUICanvas />);
    expect(getByRole('heading', { name: /GenUI Canvas/i })).toBeInTheDocument();
    expect(getByText(/Waiting for a/i)).toBeInTheDocument();
  });
});
