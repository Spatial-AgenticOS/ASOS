/**
 * Glass Brain — page-level smoke + the empty-state mind-map contract.
 *
 * Bug we are guarding against: the consciousness mind-map used to render
 * a centre dot ("FERAL") and a kind-ring SVG even when there were zero
 * in-flight entities — the dot painted on top of the empty-state text.
 * Empty state must render ONLY the centred prompt; no SVG nodes.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import GlassBrain from '../../pages/GlassBrain';
import ConsciousnessMindMap from '../../components/ConsciousnessMindMap';

beforeEach(() => {
  if (typeof ResizeObserver === 'undefined') {
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
  }
});

describe('Glass Brain', () => {
  it('renders the page heading', () => {
    const { getByRole } = renderV2(<GlassBrain />, {
      fetch: () => ({ entities: [], device_count: 0, session_count: 0, health: { status: 'ok' } }),
    });
    expect(getByRole('heading', { name: /Glass Brain/i })).toBeInTheDocument();
  });
});

describe('ConsciousnessMindMap empty state', () => {
  it('renders only the centred text — no SVG, no nodes', async () => {
    const { container, findByText } = renderV2(<ConsciousnessMindMap />, {
      fetch: () => ({ entities: [] }),
    });
    expect(await findByText(/No in-flight consciousness entities/i)).toBeInTheDocument();
    expect(container.querySelector('svg')).toBeNull();
    expect(container.querySelector('.v2-mindmap--empty')).not.toBeNull();
  });
});

describe('ConsciousnessMindMap with entities', () => {
  it('renders the SVG with at least one node circle', async () => {
    const entities = [
      {
        id: 'ent-1',
        kind: 'intent',
        status: 'active',
        summary: 'plan dinner',
        owner_session_id: 'sess-1',
        context_json: {},
      },
      {
        id: 'ent-2',
        kind: 'flow',
        status: 'active',
        summary: 'book travel',
        owner_session_id: 'sess-1',
        context_json: {},
      },
    ];
    const { container } = renderV2(<ConsciousnessMindMap />, {
      fetch: () => ({ entities }),
    });
    await waitFor(() => {
      expect(container.querySelector('svg')).not.toBeNull();
    });
    const circles = container.querySelectorAll('svg circle');
    expect(circles.length).toBeGreaterThan(0);
  });
});
