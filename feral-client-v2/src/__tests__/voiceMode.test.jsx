import { describe, it, expect } from 'vitest';
import { renderV2 } from './_helpers/renderV2';
import App from '../App';

describe('voice mode scaffolding', () => {
  it('renders the menubar voice toggle on every route', () => {
    const { getByRole } = renderV2(<App />, { route: '/chat' });
    // Starts in the off state — label is "Start voice session"
    const btn = getByRole('button', { name: /start voice session/i });
    expect(btn).toBeInTheDocument();
    expect(btn.getAttribute('aria-pressed')).toBe('false');
  });

  it('voice overlay exists in DOM but is hidden by default', () => {
    const { container } = renderV2(<App />, { route: '/chat' });
    const overlay = container.querySelector('.v2-voice-overlay');
    expect(overlay).toBeTruthy();
    expect(overlay.className).not.toContain('is-visible');
  });
});
