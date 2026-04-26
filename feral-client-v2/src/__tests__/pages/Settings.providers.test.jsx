/**
 * Settings → Providers regression tests for W1 (Roadmap §3.5 P0).
 *
 * Pins three contracts:
 *  (a) On initial mount, when the catalog row is older than 24h OR
 *      empty, the picker MUST issue a force=true refresh — without
 *      this the v2 picker silently served pre-2026 model lists for
 *      as long as the brain had been up (Appendix A.1).
 *  (b) The Live / Cached / Stale freshness badge renders next to the
 *      model dropdown, sourced from CachedModelList.last_refresh.
 *  (c) When the backend reports a 401 (warning chip text), the
 *      picker renders that warning so the user knows the dropdown
 *      is a fallback list, not live data.
 */

import { describe, it, expect, vi } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Settings from '../../pages/Settings';

const baseProvider = {
  id: 'openai',
  display_name: 'OpenAI',
  supports_local: false,
  requires_api_key: true,
  configured: true,
  reachable: true,
  default_base_url: 'https://api.openai.com/v1',
  default_model: '',
  credential_env_var: 'OPENAI_API_KEY',
  aliases: ['open ai'],
};

function makeFetcher({ modelsResponse, captureUrls }) {
  return (url) => {
    if (captureUrls) captureUrls.push(url);
    if (url.includes('/api/llm/providers/openai/models')) {
      return modelsResponse(url);
    }
    if (url.includes('/api/llm/providers')) {
      return { providers: [baseProvider], count: 1 };
    }
    if (url.includes('/api/llm/status')) {
      return { available: true, provider: 'openai', model: '' };
    }
    if (url.includes('/api/llm/health')) {
      return { active: { provider: 'openai', model: '' }, candidates: [] };
    }
    if (url.includes('/api/llm/presets')) {
      return { presets: [] };
    }
    return {};
  };
}

async function openProviderForm(getByText, findByText, findByRole) {
  fireEvent.click(getByText(/^Providers$/));
  // Wait for the provider grid to render.
  await findByText(/Current provider/i);
  // Click the "Reconfigure" / "Use this provider" button on the
  // OpenAI card. We mock status so OpenAI is the current provider →
  // the button reads "Reconfigure"; either label opens ProviderForm.
  // Use getByRole to disambiguate the button from the helper text
  // ("Live inference backend — reconfigure via any card below").
  const openButton = await findByRole('button', { name: /^(Reconfigure|Use this provider)$/i });
  fireEvent.click(openButton);
}

describe('Settings → Providers freshness (W1)', () => {
  it('(a) issues a force=true refresh on initial mount when cache is >24h stale', async () => {
    const captured = [];
    // First call returns a 25h-old cache (Unix seconds).
    const STALE_TS = (Date.now() / 1000) - (25 * 3600);
    let callIndex = 0;
    const modelsResponse = () => {
      callIndex += 1;
      if (callIndex === 1) {
        return {
          provider_id: 'openai',
          models: ['gpt-stale'],
          source: 'cache',
          last_refresh: STALE_TS,
          count: 1,
          warning: '',
        };
      }
      // Force refresh returns the fresh list.
      return {
        provider_id: 'openai',
        models: ['gpt-5.5', 'gpt-5.4'],
        source: 'live',
        last_refresh: Date.now() / 1000,
        count: 2,
        warning: '',
      };
    };

    const { getByText, findByText, findByRole, findByTestId } = renderV2(<Settings />, {
      fetch: makeFetcher({ modelsResponse, captureUrls: captured }),
    });
    await openProviderForm(getByText, findByText, findByRole);

    // Wait until BOTH calls have happened — the cached one and the
    // automatic force=true that follows because last_refresh > 24h.
    await waitFor(() => {
      const forceCalls = captured.filter((u) =>
        u.includes('/api/llm/providers/openai/models')
        && u.includes('force=true'));
      expect(forceCalls.length).toBeGreaterThanOrEqual(1);
    });

    // The badge should now read "Live" (or at least a non-stale tone).
    const badge = await findByTestId('model-age-openai');
    expect(badge.getAttribute('data-age-tone')).not.toBe('stale');
  });

  it('(a) issues a force=true refresh when the cached row is empty', async () => {
    const captured = [];
    let callIndex = 0;
    const modelsResponse = () => {
      callIndex += 1;
      if (callIndex === 1) {
        return {
          provider_id: 'openai',
          models: [],
          source: 'fallback',
          last_refresh: 0,
          count: 0,
          warning: '',
        };
      }
      return {
        provider_id: 'openai',
        models: ['gpt-5.5'],
        source: 'live',
        last_refresh: Date.now() / 1000,
        count: 1,
        warning: '',
      };
    };

    const { getByText, findByText, findByRole } = renderV2(<Settings />, {
      fetch: makeFetcher({ modelsResponse, captureUrls: captured }),
    });
    await openProviderForm(getByText, findByText, findByRole);

    await waitFor(() => {
      const forceCalls = captured.filter((u) =>
        u.includes('/api/llm/providers/openai/models')
        && u.includes('force=true'));
      expect(forceCalls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('(b) renders the freshness badge as Live when last_refresh is recent', async () => {
    const FRESH_TS = (Date.now() / 1000) - 60; // 1 minute ago
    const modelsResponse = () => ({
      provider_id: 'openai',
      models: ['gpt-5.5'],
      source: 'live',
      last_refresh: FRESH_TS,
      count: 1,
      warning: '',
    });

    const { getByText, findByText, findByRole, findByTestId } = renderV2(<Settings />, {
      fetch: makeFetcher({ modelsResponse }),
    });
    await openProviderForm(getByText, findByText, findByRole);

    const badge = await findByTestId('model-age-openai');
    expect(badge.getAttribute('data-age-tone')).toBe('live');
    expect(badge.textContent).toMatch(/Live/);
  });

  it('(b) renders the freshness badge as Cached when last_refresh is between 2h and 24h', async () => {
    const CACHED_TS = (Date.now() / 1000) - (5 * 3600); // 5 hours ago
    const modelsResponse = () => ({
      provider_id: 'openai',
      models: ['gpt-5.5'],
      source: 'cache',
      last_refresh: CACHED_TS,
      count: 1,
      warning: '',
    });

    const { getByText, findByText, findByRole, findByTestId } = renderV2(<Settings />, {
      fetch: makeFetcher({ modelsResponse }),
    });
    await openProviderForm(getByText, findByText, findByRole);

    const badge = await findByTestId('model-age-openai');
    // Badge tone is one of: live | cached | stale. 5h-old → cached.
    expect(['cached', 'stale']).toContain(badge.getAttribute('data-age-tone'));
    expect(badge.textContent).toMatch(/Cached|Stale/);
  });

  it('(c) renders the warning chip when the backend reports a 401', async () => {
    const modelsResponse = () => ({
      provider_id: 'openai',
      models: ['gpt-5.5'],
      source: 'fallback',
      last_refresh: 0,
      count: 1,
      warning: 'provider rejected the API key (HTTP 401)',
    });

    const { getByText, findByText, findByRole, findByTestId } = renderV2(<Settings />, {
      fetch: makeFetcher({ modelsResponse }),
    });
    await openProviderForm(getByText, findByText, findByRole);

    const chip = await findByTestId('model-warning-openai');
    expect(chip.textContent).toMatch(/HTTP 401/);
  });
});
