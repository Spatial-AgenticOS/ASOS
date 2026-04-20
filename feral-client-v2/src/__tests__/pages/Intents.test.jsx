import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Intents from '../../pages/Intents';

describe('Intents', () => {
  it('renders the Intents pane', () => {
    const { getByRole } = renderV2(<Intents />);
    expect(getByRole('heading', { name: /Intents/i })).toBeInTheDocument();
  });
});
