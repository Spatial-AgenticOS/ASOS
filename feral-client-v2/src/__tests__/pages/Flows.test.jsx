import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Flows from '../../pages/Flows';

describe('Flows', () => {
  it('renders the TaskFlows pane', () => {
    const { getByRole } = renderV2(<Flows />);
    expect(getByRole('heading', { name: /TaskFlows/i })).toBeInTheDocument();
  });
});
