/**
 * Web Vitals "Active sources" panel — Phase-1 truthfulness contract.
 *
 * The Today tab renders one chip per active sub-device pulled from
 * /api/dashboard, with the pipeline label mapped from the
 * capability id. Empty list = explicit "No active sources" empty
 * state (truthful — no sources connected). Populated list = a
 * `data-testid="v2-vitals-source-chip"` per row, dot tone bound
 * to the row's `live` flag straight from the brain's truth store.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Health from '../../pages/Health';

afterEach(() => {
  vi.unstubAllGlobals();
});

function dashboardWith(devices) {
  return {
    devices,
    device_count: devices.length,
    online_count: devices.length,
    paired_count: devices.length,
    paired_offline_count: 0,
    subdevices_total: devices.reduce((n, d) => n + (d.subdevices?.length || 0), 0),
    subdevices_live: devices.reduce(
      (n, d) => n + (d.subdevices || []).filter((s) => s.live).length,
      0,
    ),
    subdevices_unavailable: null,
    paired_unavailable: null,
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
  };
}

function fetchWith(dashboard, summary) {
  return (url) => {
    if (url.includes('/api/dashboard')) return dashboard;
    if (url.includes('/api/health-summary')) return summary;
    if (url.includes('/api/baseline/summary')) return { metrics_tracked: 0, recent_alerts: 0, categories: [] };
    if (url.includes('/api/baseline/metrics')) return { metrics: [] };
    if (url.includes('/api/baseline/alerts')) return { alerts: [] };
    return null;
  };
}

describe('Web Vitals — Active sources panel (Phase-1 Item 15)', () => {
  it('renders explicit empty state when the brain has no sub-devices', async () => {
    const { container } = renderV2(<Health />, {
      route: '/health',
      fetch: fetchWith(dashboardWith([]), { _ts: 0 }),
    });
    // Switch to the Today tab so TodayTab mounts.
    const todayBtn = await waitFor(() => {
      const el = Array.from(container.querySelectorAll('button')).find(
        (b) => b.textContent.trim() === 'Today',
      );
      if (!el) throw new Error('Today tab not rendered');
      return el;
    });
    todayBtn.click();
    // Empty state title + zero chips.
    await waitFor(() => {
      expect(container.textContent).toContain('No active sources');
    });
    expect(container.querySelectorAll('[data-testid="v2-vitals-source-chip"]')).toHaveLength(0);
  });

  it('renders one chip per sub-device with the mapped pipeline label', async () => {
    const dashboard = dashboardWith([
      {
        node_id: 'feral-iphone-abc',
        type: 'phone',
        subdevices: [
          { node_id: 'feral-iphone-abc', capability: 'whoop_cloud', status: 'online', provenance: 'cloud', live: true, attrs: {} },
          { node_id: 'feral-iphone-abc', capability: 'oura_cloud', status: 'online', provenance: 'cloud', live: false, attrs: {} },
        ],
      },
    ]);
    const { container } = renderV2(<Health />, {
      route: '/health',
      fetch: fetchWith(dashboard, { heart_rate: 72 }),
    });
    const todayBtn = await waitFor(() => {
      const el = Array.from(container.querySelectorAll('button')).find(
        (b) => b.textContent.trim() === 'Today',
      );
      if (!el) throw new Error('Today tab not rendered');
      return el;
    });
    todayBtn.click();
    const chips = await waitFor(() => {
      const els = container.querySelectorAll('[data-testid="v2-vitals-source-chip"]');
      if (els.length < 2) throw new Error(`expected 2 source chips, got ${els.length}`);
      return els;
    });
    const labels = Array.from(chips).map((el) => el.textContent);
    // Pipeline labels mapped from the capability id, NOT the bare
    // capability string.
    expect(labels.some((t) => t.includes('Whoop'))).toBe(true);
    expect(labels.some((t) => t.includes('Oura'))).toBe(true);
    // The live row pulses; the stale row does not.
    const whoopChip = Array.from(chips).find((el) => el.textContent.includes('Whoop'));
    const ouraChip = Array.from(chips).find((el) => el.textContent.includes('Oura'));
    expect(whoopChip.querySelector('.v2-dot--live')).toBeTruthy();
    expect(whoopChip.querySelector('.is-pulse')).toBeTruthy();
    expect(ouraChip.querySelector('.v2-dot--off')).toBeTruthy();
    expect(ouraChip.querySelector('.is-pulse')).toBeFalsy();
  });
});
