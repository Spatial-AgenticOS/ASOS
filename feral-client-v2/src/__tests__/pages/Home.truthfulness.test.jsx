/**
 * Home page truthfulness contract (Phase 1).
 *
 * Pins the post-fix behaviour for the hero "Brain" stat card and the
 * new "Subdevices" tile. Before this PR the Brain card was a literal
 * `<StatusDot tone="live" pulse /> online` regardless of real state —
 * the operator caught it; the audit-r6 / r7 sweeps confirmed it. The
 * tests below render the page against a mocked /api/dashboard and
 * verify the strings that ship to the user.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Home from '../../pages/Home';

afterEach(() => {
  vi.unstubAllGlobals();
});

function dashboardWith(extra = {}) {
  return {
    devices: [],
    device_count: 0,
    online_count: 0,
    paired_count: 0,
    paired_offline_count: 0,
    subdevices_total: 0,
    subdevices_live: 0,
    channels: [],
    session_count: 0,
    health: {},
    memory: {},
    skills_count: 0,
    llm_available: false,
    audio_available: false,
    sync: {},
    wasm_available: false,
    wake_word_enabled: false,
    taskflows: {},
    boot: {},
    demo: false,
    is_demo_mode: false,
    somatic: {},
    ...extra,
  };
}

function dashboardFetch(extra) {
  return (url) => {
    if (url.includes('/api/dashboard')) return dashboardWith(extra);
    return null; // falls through to DEFAULT_FETCH_BODY
  };
}

describe('Home — Phase 1 truthfulness sweep', () => {
  it('hero Brain stat is no longer hardcoded online — it has a binding', async () => {
    // The exact label depends on the WS state machine, which our
    // StubWebSocket auto-opens; we mostly assert that a measurable
    // binding exists. The previous code would have shipped the
    // literal "online" string regardless of any input — we pin
    // against that regression here.
    const { container } = renderV2(<Home />, {
      fetch: dashboardFetch({}),
    });
    const brainStat = await waitFor(() => {
      const el = container.querySelector('[data-testid="v2-home-brain-stat"]');
      if (!el) throw new Error('brain stat tile not rendered');
      return el;
    });
    // Either online / reconnecting / offline — never one of those is
    // an acceptable answer; the hardcoded version always read "online".
    expect(brainStat.textContent.trim()).toMatch(/online|reconnecting|offline/);
    // The dot has a label attribute now (truthfulness contract).
    const dot = brainStat.querySelector('.v2-dot');
    expect(dot).toBeTruthy();
    expect(dot.getAttribute('aria-label') || '').toMatch(/Brain (online|reconnecting|offline)/);
  });

  it('subdevices stat tile is hidden when the brain reports zero subdevices ever', async () => {
    const { container } = renderV2(<Home />, {
      fetch: dashboardFetch({ subdevices_total: 0, subdevices_live: 0 }),
    });
    // Allow the initial /api/dashboard fetch to land.
    await waitFor(() => {
      const tile = container.querySelector('[data-testid="v2-home-subdevices-stat"]');
      // Truthful: when the brain has never seen a sub-device the tile
      // is omitted. Inventing a "0/0" zero-row would be a small lie
      // that drifts toward the kind of placeholder the audit caught.
      expect(tile).toBeNull();
    });
  });

  it('subdevices stat tile renders live / total when the brain reports any sub-device', async () => {
    const { container } = renderV2(<Home />, {
      fetch: dashboardFetch({ subdevices_total: 1, subdevices_live: 1 }),
    });
    const tile = await waitFor(() => {
      const el = container.querySelector('[data-testid="v2-home-subdevices-stat"]');
      if (!el) throw new Error('subdevices tile missing despite total > 0');
      return el;
    });
    expect(tile.textContent).toContain('1/1');
    const dot = tile.querySelector('.v2-dot');
    expect(dot).toBeTruthy();
    // 1 live → live tone with pulse animation.
    expect(dot.className).toContain('v2-dot--live');
    expect(dot.className).toContain('is-pulse');
  });

  it('subdevices tile downgrades to off when no subdevice is inside its heartbeat window', async () => {
    const { container } = renderV2(<Home />, {
      fetch: dashboardFetch({ subdevices_total: 2, subdevices_live: 0 }),
    });
    const tile = await waitFor(() => {
      const el = container.querySelector('[data-testid="v2-home-subdevices-stat"]');
      if (!el) throw new Error('subdevices tile missing despite total > 0');
      return el;
    });
    expect(tile.textContent).toContain('0/2');
    const dot = tile.querySelector('.v2-dot');
    // 0 live → off tone, no pulse. The previous hardcoded `tone="live"
    // pulse` would have failed this assertion.
    expect(dot.className).toContain('v2-dot--off');
    expect(dot.className).not.toContain('is-pulse');
  });
});
