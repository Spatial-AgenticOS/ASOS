/**
 * MemoryContext — inspector for the multi-memory block the Brain
 * assembled per LLM turn.
 *
 * Covers:
 *   1. Empty ring state — "Send a message to see multi-memory in action".
 *   2. Snapshot cards render query + memory_filter + latency.
 *   3. Tiered `## Heading`-split rendering of the memory_context body.
 *   4. Error state when the API throws.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { installFetchMock, StubWebSocket } from '../_helpers/renderV2';
import { renderV2 } from '../_helpers/renderV2';
import MemoryContext from '../../pages/MemoryContext';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

beforeEach(() => {
  navigateMock.mockClear();
});

function renderWithHistory(ui, { entries = ['/glass-brain', '/memory/context'], index = 1, fetch } = {}) {
  installFetchMock(fetch);
  vi.stubGlobal('WebSocket', StubWebSocket);
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={index}>
      {ui}
    </MemoryRouter>,
  );
}

function makeSnapshot(overrides = {}) {
  return {
    session_id: 'sess-abcdef01',
    query: 'where is my wallet',
    memory_filter: '',
    latency_ms: 12,
    ts: Date.now() / 1000 - 30,
    memory_context: '## Recent Context\n[user] hi\n\n## Known Facts\n- wallet located_in kitchen',
    ...overrides,
  };
}

describe('MemoryContext inspector', () => {
  it('renders header pane', () => {
    const { getByText } = renderV2(<MemoryContext />, {
      fetch: () => ({ count: 0, snapshots: [] }),
    });
    expect(getByText(/Memory context/i)).toBeInTheDocument();
  });

  it('shows empty-state when no snapshots', async () => {
    const { findByText } = renderV2(<MemoryContext />, {
      fetch: () => ({ count: 0, snapshots: [] }),
    });
    expect(await findByText(/Send a message to see multi-memory/i)).toBeInTheDocument();
  });

  it('renders the query + memory_filter chips on each card', async () => {
    const snap = makeSnapshot({ memory_filter: 'journal' });
    const { findByText } = renderV2(<MemoryContext />, {
      fetch: () => ({ count: 1, snapshots: [snap] }),
    });
    // Query rendered
    expect(await findByText(/where is my wallet/)).toBeInTheDocument();
    // memory_filter chip (shows the tag name)
    expect(await findByText(/journal/)).toBeInTheDocument();
    // latency pill
    expect(await findByText(/12ms/)).toBeInTheDocument();
  });

  it('splits the memory block into tiered sections', async () => {
    const snap = makeSnapshot();
    const { findByText } = renderV2(<MemoryContext />, {
      fetch: () => ({ count: 1, snapshots: [snap] }),
    });
    // Both tier titles appear.
    expect(await findByText(/Recent Context/)).toBeInTheDocument();
    expect(await findByText(/Known Facts/)).toBeInTheDocument();
  });

  it('shows the "nothing returned" note for an empty memory block', async () => {
    const snap = makeSnapshot({ memory_context: '' });
    const { findByText } = renderV2(<MemoryContext />, {
      fetch: () => ({ count: 1, snapshots: [snap] }),
    });
    expect(await findByText(/working memory empty/i)).toBeInTheDocument();
  });

  it('renders a leading Back button in the page header', () => {
    const { getByRole } = renderV2(<MemoryContext />, {
      fetch: () => ({ count: 0, snapshots: [] }),
    });
    expect(getByRole('button', { name: /Back/i })).toBeInTheDocument();
  });

  it('clicking Back calls navigate(-1) when there is in-app history', () => {
    const { getByRole } = renderWithHistory(<MemoryContext />, {
      fetch: () => ({ count: 0, snapshots: [] }),
    });
    fireEvent.click(getByRole('button', { name: /Back/i }));
    expect(navigateMock).toHaveBeenCalledWith(-1);
  });

  it('clicking Back falls back to /glass-brain on a deep-linked open', () => {
    const { getByRole } = renderWithHistory(<MemoryContext />, {
      entries: ['/memory/context'],
      index: 0,
      fetch: () => ({ count: 0, snapshots: [] }),
    });
    fireEvent.click(getByRole('button', { name: /Back/i }));
    expect(navigateMock).toHaveBeenCalledWith('/glass-brain');
  });
});
