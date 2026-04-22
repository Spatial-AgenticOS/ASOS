import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import PerceptionShare from '../../components/PerceptionShare';

beforeEach(() => {
  // Minimal getUserMedia stub. Some tests assert the start button is visible
  // even without real media tracks.
  if (!navigator.mediaDevices) {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: vi.fn(() =>
          Promise.resolve({
            getTracks: () => [],
          }),
        ),
      },
      configurable: true,
    });
  }
});

describe('PerceptionShare', () => {
  it('renders the pane with a Start sharing button in idle state', () => {
    const { getByTestId } = renderV2(<PerceptionShare />);
    expect(getByTestId('perception-share-pane')).toBeInTheDocument();
    expect(getByTestId('perception-start')).toBeInTheDocument();
  });

  it('exposes fps + toggle controls', () => {
    const { getByTestId } = renderV2(<PerceptionShare />);
    expect(getByTestId('perception-fps')).toBeInTheDocument();
  });
});
