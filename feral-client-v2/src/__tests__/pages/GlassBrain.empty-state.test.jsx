/**
 * Glass Brain — empty-state geometry contract.
 *
 * User-reported bug:
 *
 *   On /glass-brain when the consciousness graph is empty, a coloured
 *   ball overlapped the centred empty-state prompt ("No in-flight
 *   consciousness entities…").
 *
 * Root-cause analysis (this PR):
 *
 *   The offender is the legend dot block at GlassBrain.jsx:141-152.
 *   `kindRows` always retained the
 *   `intent` and `flow` rows even when their counts were 0, so two
 *   `.v2-glass-brain-legend-dot` spans (each `border-radius: 50%`,
 *   `width: 8px`) rendered inside the Pane's `actions` slot. On
 *   narrower viewports the pane header shrunk and the dots bled into
 *   the body region where the absolutely-centred `.v2-mindmap-empty`
 *   text lives — producing the "blue ball over the empty state"
 *   the user reported.
 *
 * Fix shape — Option A (smaller diff than Option B):
 *
 *   Conditionally render the legend in the Pane's `actions` slot only
 *   when there is at least one in-flight entity. When the graph is
 *   empty there is nothing to legend, so we hide the row entirely.
 *
 * Regression contract enforced here:
 *
 *   In the empty-graph state, no element with `border-radius: 50%`
 *   AND a non-zero rendered width may intersect the bounding box of
 *   the `.v2-mindmap-empty` text. The test mocks
 *   `Element.prototype.getBoundingClientRect` (jsdom doesn't compute
 *   layout) so that, IF the offending dots ever rendered again, their
 *   geometry would overlap the centred empty-state text and the
 *   assertion would fail. Post-fix, the dots simply don't render and
 *   the assertion is vacuously satisfied.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import GlassBrain from '../../pages/GlassBrain';
import ConsciousnessMindMap from '../../components/ConsciousnessMindMap';

function rect(left, top, width, height) {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON() { return this; },
  };
}

function rectsIntersect(a, b) {
  return !(a.right <= b.left
    || a.left >= b.right
    || a.bottom <= b.top
    || a.top >= b.bottom);
}

let originalGetBoundingClientRect;

beforeEach(() => {
  if (typeof ResizeObserver === 'undefined') {
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
  }

  originalGetBoundingClientRect = Element.prototype.getBoundingClientRect;

  // Simulate the layout the user reported in their screenshot: the
  // empty-state text is absolutely centred in the mind-map body, and
  // the offending dots — IF rendered — would land in or overlap the
  // body region (rather than staying tucked into the pane header on
  // a wider viewport). This way the test fails before the fix and
  // passes after it.
  Element.prototype.getBoundingClientRect = function patchedGetBCR() {
    const cls = this.className && typeof this.className === 'string'
      ? this.className
      : (this.getAttribute && this.getAttribute('class')) || '';

    if (cls.includes('v2-mindmap-empty')) {
      return rect(200, 240, 400, 60);
    }
    if (cls.includes('v2-mindmap')) {
      return rect(0, 200, 800, 280);
    }
    if (cls.includes('v2-glass-brain-legend-dot')) {
      // Pre-fix bleed-through position: dot drifts into the body
      // region where the empty-state prompt is centred.
      return rect(380, 260, 8, 8);
    }
    if (this.tagName && this.tagName.toLowerCase() === 'circle') {
      const r = parseFloat(this.getAttribute('r') || '0');
      const cx = parseFloat(this.getAttribute('cx') || '400');
      const cy = parseFloat(this.getAttribute('cy') || '270');
      return rect(cx - r, cy - r, r * 2, r * 2);
    }
    return rect(0, 0, 0, 0);
  };
});

afterEach(() => {
  Element.prototype.getBoundingClientRect = originalGetBoundingClientRect;
});

describe('Glass Brain empty state — no overlapping dots', () => {
  it('the empty mind-map renders only the centred prompt — no SVG, no centre dot', async () => {
    const { container, findByText } = renderV2(<ConsciousnessMindMap />, {
      fetch: () => ({ entities: [] }),
    });
    expect(await findByText(/No in-flight consciousness entities/i)).toBeInTheDocument();
    expect(container.querySelector('svg')).toBeNull();
    expect(container.querySelectorAll('circle').length).toBe(0);
  });

  it('on the full GlassBrain page with empty entities, no border-radius:50% sibling overlaps the empty-state text bbox', async () => {
    const { container } = renderV2(<GlassBrain />, {
      fetch: () => ({
        entities: [],
        device_count: 0,
        session_count: 0,
        health: { status: 'ok' },
      }),
    });

    // Wait for the empty-state prompt to land in the DOM (the
    // ConsciousnessMindMap's first refresh resolves to entities=[]).
    await waitFor(() => {
      expect(container.querySelector('.v2-mindmap-empty')).not.toBeNull();
    });

    const empty = container.querySelector('.v2-mindmap-empty');
    const emptyRect = empty.getBoundingClientRect();
    expect(emptyRect.width).toBeGreaterThan(0);
    expect(emptyRect.height).toBeGreaterThan(0);

    // Enumerate every plausible "dot" — anything explicitly styled
    // with `border-radius: 50%` in the v2 stylesheet that could
    // conceivably appear inside the GlassBrain render tree, plus
    // any raw SVG <circle>. jsdom does not load the page CSS and
    // does not resolve `getComputedStyle` for external stylesheets,
    // so we use class-name selectors as a proxy and SVG <circle>
    // for the mind-map's own primitives.
    const dotSelectors = [
      '.v2-glass-brain-legend-dot',
      '.v2-dot',
      '.v2-menubar-dot',
      '.v2-device-dot',
      '.v2-voice-dot',
      'svg circle',
    ];

    const dots = [];
    for (const sel of dotSelectors) {
      container.querySelectorAll(sel).forEach((el) => dots.push(el));
    }

    for (const dot of dots) {
      const dotRect = dot.getBoundingClientRect();
      if (dotRect.width === 0 || dotRect.height === 0) continue;
      const overlaps = rectsIntersect(dotRect, emptyRect);
      expect(
        overlaps,
        `Element ${dot.outerHTML?.slice(0, 120) || dot.tagName} (rect ${JSON.stringify(dotRect)}) overlaps empty-state ${JSON.stringify(emptyRect)}`,
      ).toBe(false);
    }
  });

  it('with at least one in-flight entity the legend reappears (so the fix is conditional, not a deletion)', async () => {
    const entities = [{
      id: 'ent-1',
      kind: 'intent',
      status: 'active',
      summary: 'plan dinner',
      owner_session_id: 'sess-1',
      context_json: {},
    }];
    const { container, findByText } = renderV2(<GlassBrain />, {
      fetch: (url) => {
        if (url.includes('/api/consciousness/state')) return { entities };
        return { entities: [], device_count: 0, session_count: 0, health: { status: 'ok' } };
      },
    });

    // The page mounts before the consciousness fetch resolves; the
    // legend appears once entities arrive.
    await waitFor(() => {
      expect(container.querySelector('.v2-glass-brain-legend')).not.toBeNull();
    });
    expect(container.querySelectorAll('.v2-glass-brain-legend-dot').length).toBeGreaterThan(0);
    // And the empty-state prompt is gone (the SVG mind-map renders).
    expect(container.querySelector('.v2-mindmap-empty')).toBeNull();
    // findByText is exposed so the linter doesn't flag the unused destructure.
    void findByText;
  });
});
