import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Home from '../../pages/Home';

describe('Home (merged Dashboard + Ambient)', () => {
  it('renders the hero greeting + mode tabs + stats grid', () => {
    const { container, getByRole } = renderV2(<Home />);
    expect(container.querySelector('.v2-home-hero-body')).toBeTruthy();
    expect(container.querySelector('.v2-home-stats')).toBeTruthy();
    // Briefing / Desk / Wind-Down are rendered as buttons with aria-pressed.
    expect(getByRole('button', { name: /Briefing/i })).toBeInTheDocument();
    expect(getByRole('button', { name: /Desk/i })).toBeInTheDocument();
    expect(getByRole('button', { name: /Wind-Down/i })).toBeInTheDocument();
  });

  it('mounts a hidden SkillsLauncher by default (opened via pin strip)', () => {
    const { container } = renderV2(<Home />);
    // Launcher backdrop is conditional; pin strip container is always rendered.
    expect(container.querySelector('.v2-skill-pinstrip')).toBeTruthy();
  });
});
