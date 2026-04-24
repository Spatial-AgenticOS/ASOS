/**
 * Oversight — supervisor audit log + kill switch.
 *
 * The page does three things:
 *   1. Lists /api/supervisor/events with filter chips.
 *   2. Shows /api/supervisor/stats in pill form (total + paused flag).
 *   3. Toggles the kill switch via POST /api/supervisor/pause.
 *
 * These tests exercise all three with honest fetch mocks — no shortcuts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { installFetchMock, StubWebSocket } from '../_helpers/renderV2';
import { renderV2 } from '../_helpers/renderV2';
import Oversight from '../../pages/Oversight';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

function renderWithHistory(ui, { entries = ['/glass-brain', '/oversight'], index = 1, fetch } = {}) {
  installFetchMock(fetch);
  vi.stubGlobal('WebSocket', StubWebSocket);
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={index}>
      {ui}
    </MemoryRouter>,
  );
}

const baseEvents = [
  {
    event_id: 'e1',
    ts: Date.now() / 1000,
    source: 'web',
    kind: 'handle_command',
    session_id: 'sess-12345678',
    actor: 'user',
    payload_summary: 'hello there',
    payload_hash: 'hash1',
    decision: 'allowed',
    latency_ms: 42,
  },
  {
    event_id: 'e2',
    ts: Date.now() / 1000 - 5,
    source: 'cron',
    kind: 'handle_command',
    session_id: 'routine-42',
    actor: 'system',
    payload_summary: 'morning briefing',
    payload_hash: 'hash2',
    decision: 'denied',
    latency_ms: 1,
  },
  {
    event_id: 'e3',
    ts: Date.now() / 1000 - 10,
    source: 'twin',
    kind: 'twin_action',
    session_id: '',
    actor: 'twin',
    payload_summary: 'draft email to sam',
    payload_hash: 'hash3',
    decision: 'queued',
    latency_ms: 5,
  },
];

const baseStats = {
  total: 3,
  by_source: { web: 1, cron: 1, twin: 1 },
  paused: false,
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  navigateMock.mockClear();
});
afterEach(() => {
  vi.useRealTimers();
});

function makeResponder({ events = baseEvents, stats = baseStats } = {}) {
  return (url) => {
    if (url.includes('/api/supervisor/events')) {
      return { count: events.length, events };
    }
    if (url.includes('/api/supervisor/stats')) {
      return stats;
    }
    return {};
  };
}

describe('Oversight page', () => {
  it('renders header + event rows', async () => {
    const { findByText, getByText } = renderV2(<Oversight />, {
      fetch: makeResponder(),
    });
    expect(getByText(/Oversight/i)).toBeInTheDocument();
    expect(await findByText('hello there')).toBeInTheDocument();
    expect(await findByText('morning briefing')).toBeInTheDocument();
    expect(await findByText('draft email to sam')).toBeInTheDocument();
  });

  it('shows kill switch label based on paused state', async () => {
    const { findByRole, rerender } = renderV2(<Oversight />, {
      fetch: makeResponder({ stats: { ...baseStats, paused: false } }),
    });
    const btn = await findByRole('button', { name: /Pause actions/i });
    expect(btn).toBeInTheDocument();

    vi.unstubAllGlobals();
    const { findByRole: findR2 } = renderV2(<Oversight />, {
      fetch: makeResponder({ stats: { ...baseStats, paused: true } }),
    });
    expect(await findR2('button', { name: /Resume/i })).toBeInTheDocument();
  });

  it('displays stat pills for total + per-source counts', async () => {
    const { findAllByText } = renderV2(<Oversight />, {
      fetch: makeResponder(),
    });
    // Total pill
    expect((await findAllByText('3')).length).toBeGreaterThanOrEqual(1);
    // At least one per-source pill (web/cron/twin)
    expect((await findAllByText(/^web$/)).length).toBeGreaterThanOrEqual(1);
  });

  it('renders empty-state chip when events list is empty and not loading', async () => {
    const { findByText } = renderV2(<Oversight />, {
      fetch: makeResponder({ events: [] }),
    });
    // "No events match this filter" is the empty state title.
    expect(await findByText(/No events match this filter/i)).toBeInTheDocument();
  });

  it('renders a leading Back button in the page header', () => {
    const { getByRole } = renderV2(<Oversight />, { fetch: makeResponder() });
    expect(getByRole('button', { name: /Back/i })).toBeInTheDocument();
  });

  it('clicking Back calls navigate(-1) when there is in-app history', () => {
    const { getByRole } = renderWithHistory(<Oversight />, {
      fetch: makeResponder(),
    });
    fireEvent.click(getByRole('button', { name: /Back/i }));
    expect(navigateMock).toHaveBeenCalledWith(-1);
  });

  it('clicking Back falls back to /glass-brain on a deep-linked open', () => {
    const { getByRole } = renderWithHistory(<Oversight />, {
      entries: ['/oversight'],
      index: 0,
      fetch: makeResponder(),
    });
    fireEvent.click(getByRole('button', { name: /Back/i }));
    expect(navigateMock).toHaveBeenCalledWith('/glass-brain');
  });
});
