import { describe, it, expect } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Settings from '../../pages/Settings';

const catalogProviders = [
  {
    id: 'openai',
    display_name: 'OpenAI',
    supports_local: false,
    requires_api_key: true,
    configured: true,
    reachable: true,
    default_base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o-mini',
    credential_env_var: 'OPENAI_API_KEY',
    aliases: ['open ai'],
  },
  {
    id: 'anthropic',
    display_name: 'Anthropic',
    supports_local: false,
    requires_api_key: true,
    configured: false,
    reachable: null,
    default_base_url: 'https://api.anthropic.com/v1',
    default_model: 'claude-sonnet-4-20250514',
    credential_env_var: 'ANTHROPIC_API_KEY',
    aliases: [],
  },
  {
    id: 'ollama',
    display_name: 'Ollama',
    supports_local: true,
    requires_api_key: false,
    configured: true,
    reachable: false,
    default_base_url: 'http://localhost:11434/v1',
    default_model: 'llama3',
    credential_env_var: '',
    aliases: ['local'],
  },
];

const healthSnapshot = {
  active: { provider: 'openai', model: 'gpt-4o-mini', has_key: true, available: true, base_url: '' },
  candidates: [
    { provider: 'openai', model: 'gpt-4o-mini', has_key: true, in_cooldown: false, cooldown_remaining: 0 },
    { provider: 'anthropic', model: 'claude', has_key: false, in_cooldown: false, cooldown_remaining: 0 },
    { provider: 'ollama', model: 'llama3', has_key: true, in_cooldown: true, cooldown_remaining: 42 },
  ],
  fallback_providers: ['ollama'],
  total_available: 1,
};

function providersResponder(url) {
  if (url.includes('/api/llm/providers')) {
    return { providers: catalogProviders, count: catalogProviders.length };
  }
  if (url.includes('/api/llm/status')) {
    return { available: true, provider: 'openai', model: 'gpt-4o-mini' };
  }
  if (url.includes('/api/llm/presets')) {
    return { presets: [{ id: 'openai_default', label: 'OpenAI default' }] };
  }
  if (url.includes('/api/llm/health')) {
    return healthSnapshot;
  }
  if (url.includes('/api/memory/backend')) {
    return { backend: 'sqlite_vec', available: ['sqlite_vec', 'chroma', 'qdrant'], configured: {} };
  }
  if (url.includes('/api/identity')) {
    return { name: 'FERAL', personality: '', rules: [], greeting_style: '', voice: {} };
  }
  if (url.includes('/api/about-me')) {
    return { facts: [] };
  }
  return {};
}

describe('Settings', () => {
  it('renders the settings split layout with all sections including Self + Twin', () => {
    const { getAllByText, getByText } = renderV2(<Settings />);
    expect(getAllByText(/^Self$/i).length).toBeGreaterThan(0);
    for (const s of ['General', 'Providers', 'Memory', 'Channels', 'Autonomy', 'Voice', 'Twin']) {
      expect(getByText(s)).toBeInTheDocument();
    }
  });

  it('exposes a Self button in the settings nav that opens the Self editors', () => {
    const { getAllByText } = renderV2(<Settings />);
    expect(getAllByText(/IDENTITY \/ SOUL \/ MEMORY \/ ABOUT-ME/i).length).toBeGreaterThan(0);
  });

  it('exposes an ABOUT ME tab inside the Self workspace', () => {
    const { getByRole } = renderV2(<Settings />);
    expect(getByRole('tab', { name: /ABOUT ME/i })).toBeInTheDocument();
  });

  it('Providers section renders the catalog card grid + current-provider banner', async () => {
    const { getByText, findAllByText, findByText } = renderV2(<Settings />, {
      fetch: providersResponder,
    });
    // Switch to Providers section.
    fireEvent.click(getByText(/^Providers$/));
    // Current provider card.
    expect(await findByText(/Current provider/i)).toBeInTheDocument();
    // Every built-in descriptor exposed (sanity check a few).
    expect((await findAllByText(/OpenAI/i)).length).toBeGreaterThan(0);
    expect((await findAllByText(/Anthropic/i)).length).toBeGreaterThan(0);
    expect((await findAllByText(/Ollama/i)).length).toBeGreaterThan(0);
  });

  it('Providers section exposes a Fallbacks card with cooldown state', async () => {
    const { getByText, findByText } = renderV2(<Settings />, {
      fetch: providersResponder,
    });
    fireEvent.click(getByText(/^Providers$/));
    expect(await findByText(/Fallbacks/i)).toBeInTheDocument();
    // Cooldown hint from health_snapshot (ollama in_cooldown).
    expect(await findByText(/cooling down 42s/)).toBeInTheDocument();
  });

  it('Providers section shows preset buttons when the API returns presets', async () => {
    const { getByText, findByText } = renderV2(<Settings />, {
      fetch: providersResponder,
    });
    fireEvent.click(getByText(/^Providers$/));
    expect(await findByText(/OpenAI default/)).toBeInTheDocument();
  });

  it('Memory section renders the backend picker', async () => {
    const { getByText, findByText } = renderV2(<Settings />, {
      fetch: providersResponder,
    });
    fireEvent.click(getByText(/^Memory$/));
    // The MemorySection renders the backend name somewhere.
    expect(await findByText(/sqlite_vec/i)).toBeInTheDocument();
  });

  // ── Twin honesty (no executor wired → no theatre) ────────────
  // Pre-2026.4.29 the Twin section rendered nine canned domains
  // regardless of whether a backing executor existed. These tests pin
  // the new contract: empty payload → empty-state, wired executor →
  // toggles.

  it('Twin section renders the empty-state when /api/twin/policies returns empty', async () => {
    const fetcher = (url) => {
      if (url.includes('/api/twin/policies')) {
        return { policies: [], disconnected: [], available: [] };
      }
      if (url.includes('/api/twin/approvals')) return { approvals: [] };
      if (url.includes('/api/supervisor/stats')) return { paused: false };
      return providersResponder(url);
    };
    const { getByText, findByTestId, queryByText } = renderV2(<Settings />, {
      fetch: fetcher,
    });
    fireEvent.click(getByText(/^Twin$/));
    expect(await findByTestId('twin-empty-state')).toBeInTheDocument();
    // None of the canned domain labels should appear when nothing is wired.
    await waitFor(() => {
      expect(queryByText(/Respond to iMessage/i)).toBeNull();
      expect(queryByText(/Reply on Slack/i)).toBeNull();
    });
  });

  it('Twin section renders rows + toggles when a real executor exists', async () => {
    const fetcher = (url) => {
      if (url.includes('/api/twin/policies')) {
        return {
          policies: [
            {
              domain: 'reply_slack',
              mode: 'draft_only',
              time_windows: [],
              max_per_day: 10,
              requires_user_online: false,
              wired: true,
              label: '',
            },
          ],
          disconnected: [],
          available: [{ domain: 'reply_slack', label: '' }],
        };
      }
      if (url.includes('/api/twin/approvals')) return { approvals: [] };
      if (url.includes('/api/supervisor/stats')) return { paused: false };
      return providersResponder(url);
    };
    const { getByText, findAllByText, findByText, queryByTestId } = renderV2(
      <Settings />,
      { fetch: fetcher },
    );
    fireEvent.click(getByText(/^Twin$/));
    // The row label must render and the empty-state must NOT.
    expect((await findAllByText(/Reply on Slack/i)).length).toBeGreaterThan(0);
    expect(queryByTestId('twin-empty-state')).toBeNull();
    // Draft / Auto / Off toggles render against the wired row.
    expect(await findByText('Draft')).toBeInTheDocument();
    expect(await findByText('Auto')).toBeInTheDocument();
    expect(await findByText('Off')).toBeInTheDocument();
  });

  it('Twin section dims a row that lost its executor (disconnected bucket)', async () => {
    const fetcher = (url) => {
      if (url.includes('/api/twin/policies')) {
        return {
          policies: [],
          disconnected: [
            {
              domain: 'reply_slack',
              mode: 'auto_send',
              time_windows: [],
              max_per_day: 10,
              requires_user_online: false,
              wired: false,
              label: '',
            },
          ],
          available: [],
        };
      }
      if (url.includes('/api/twin/approvals')) return { approvals: [] };
      if (url.includes('/api/supervisor/stats')) return { paused: false };
      return providersResponder(url);
    };
    const { getByText, findByTestId, findAllByText } = renderV2(<Settings />, {
      fetch: fetcher,
    });
    fireEvent.click(getByText(/^Twin$/));
    expect(await findByTestId('twin-disconnected')).toBeInTheDocument();
    expect((await findAllByText(/Disconnected/i)).length).toBeGreaterThan(0);
  });
});
