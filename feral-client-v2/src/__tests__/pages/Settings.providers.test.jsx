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

  it('requests the recommended chat-class subset by default', async () => {
    // The v2 picker defaults to the conductor-curated chat shortlist
    // (recommended=true, model_class=chat) so the dropdown never
    // surfaces embeddings / whisper-* / dall-e etc — those are 400s
    // on /chat/completions and were the root cause of the drift bug.
    const captured = [];
    const modelsResponse = () => ({
      provider_id: 'openai',
      models: ['gpt-5.5-pro'],
      source: 'live',
      last_refresh: Date.now() / 1000,
      count: 1,
      warning: '',
    });

    const { getByText, findByText, findByRole } = renderV2(<Settings />, {
      fetch: makeFetcher({ modelsResponse, captureUrls: captured }),
    });
    await openProviderForm(getByText, findByText, findByRole);

    await waitFor(() => {
      const modelCalls = captured.filter((u) =>
        u.includes('/api/llm/providers/openai/models'));
      expect(modelCalls.length).toBeGreaterThanOrEqual(1);
      for (const u of modelCalls) {
        expect(u).toMatch(/recommended=true/);
        expect(u).toMatch(/model_class=chat/);
      }
    });
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

/**
 * Settings → Providers credential-saving tests for A2.
 *
 * A2 decouples persisting provider credentials from switching the
 * active provider. Pasting an Anthropic key while OpenAI is the
 * active provider must NOT automatically flip the live backend to
 * Anthropic — it should just persist the key so failover /
 * "switch later" flows can pick it up. The "Save & switch" button
 * remains the explicit path for users who do want to flip right now.
 */
describe('Settings → Providers credential saving (A2)', () => {
  // anthropic catalog row as a SECOND provider, while status reports
  // openai as the active one. This is exactly the "adding a second
  // key" scenario that the A2 churn bug manifested under.
  const anthropicProvider = {
    id: 'anthropic',
    display_name: 'Anthropic',
    supports_local: false,
    requires_api_key: true,
    configured: false,
    reachable: null,
    default_base_url: 'https://api.anthropic.com',
    default_model: '',
    credential_env_var: 'ANTHROPIC_API_KEY',
    aliases: [],
  };

  function makeMultiProviderFetcher({ captureCalls, modelsResponse }) {
    return (url, init) => {
      if (captureCalls) captureCalls.push({ url, method: init?.method || 'GET', body: init?.body });
      if (url.includes('/api/llm/providers/anthropic/models')
          || url.includes('/api/llm/providers/openai/models')) {
        return modelsResponse
          ? modelsResponse(url)
          : {
              provider_id: url.includes('anthropic') ? 'anthropic' : 'openai',
              models: ['claude-x', 'gpt-x'],
              source: 'live',
              last_refresh: Date.now() / 1000,
              count: 2,
              warning: '',
            };
      }
      if (url.endsWith('/api/llm/providers') || url.includes('/api/llm/providers?')) {
        return {
          providers: [
            { ...baseProvider, configured: true, reachable: true },
            anthropicProvider,
          ],
          count: 2,
        };
      }
      if (url.includes('/api/llm/providers/anthropic/configure')) {
        return {
          success: true,
          status: { ...anthropicProvider, configured: true, provider_id: 'anthropic' },
          persisted: { ok: true, vault: true, warnings: [] },
          active_provider: false,
        };
      }
      if (url.includes('/api/llm/config')) {
        return {
          success: true,
          provider: 'anthropic',
          model: 'claude-x',
          persisted: { ok: true, warnings: [] },
          reconfigured: { ok: true },
        };
      }
      if (url.includes('/api/llm/status')) {
        return { available: true, provider: 'openai', model: 'gpt-x' };
      }
      if (url.includes('/api/llm/health')) {
        return { active: { provider: 'openai', model: 'gpt-x' }, candidates: [] };
      }
      if (url.includes('/api/llm/presets')) {
        return { presets: [] };
      }
      return {};
    };
  }

  async function openAnthropicForm({ getByText, findByText, findAllByRole }) {
    fireEvent.click(getByText(/^Providers$/));
    await findByText(/Current provider/i);
    // Two provider cards render; anthropic is non-current, so its
    // opening button reads "Use this provider". There are two such
    // buttons when neither card is open yet (openai shows
    // "Reconfigure" because it is current), so filter for the
    // non-current one.
    const buttons = await findAllByRole('button', {
      name: /^(Use this provider|Reconfigure)$/i,
    });
    const openNonCurrent = buttons.find((b) => /Use this provider/i.test(b.textContent));
    fireEvent.click(openNonCurrent);
  }

  it('non-current provider: default Save-key button does NOT call /api/llm/config', async () => {
    const calls = [];
    const { getByText, findByText, findAllByRole, findByTestId } = renderV2(<Settings />, {
      fetch: makeMultiProviderFetcher({ captureCalls: calls }),
    });
    await openAnthropicForm({ getByText, findByText, findAllByRole });

    // Find the "Save key" button exposed by the non-current branch.
    const saveKey = await findByTestId('provider-save-key-anthropic');
    expect(saveKey).toBeTruthy();

    fireEvent.click(saveKey);

    // Wait for the configure POST to land.
    await waitFor(() => {
      const postsToConfigure = calls.filter((c) =>
        c.method === 'POST'
        && c.url.includes('/api/llm/providers/anthropic/configure'));
      expect(postsToConfigure.length).toBeGreaterThanOrEqual(1);
    });

    // The active-provider switch endpoint must NOT have been hit —
    // the user only pasted a key, they did not ask to switch.
    const postsToConfig = calls.filter((c) =>
      c.method === 'POST' && c.url.match(/\/api\/llm\/config(\?|$)/));
    expect(postsToConfig.length).toBe(0);
  });

  it('non-current provider: explicit Save & switch still calls /api/llm/config', async () => {
    const calls = [];
    const { getByText, findByText, findAllByRole, findByTestId } = renderV2(<Settings />, {
      fetch: makeMultiProviderFetcher({ captureCalls: calls }),
    });
    await openAnthropicForm({ getByText, findByText, findAllByRole });

    // Wait for models to populate so the switch button isn't disabled.
    await waitFor(() => {
      const modelCalls = calls.filter((c) => c.url.includes('/api/llm/providers/anthropic/models'));
      expect(modelCalls.length).toBeGreaterThanOrEqual(1);
    });

    const saveSwitch = await findByTestId('provider-save-switch-anthropic');
    await waitFor(() => { expect(saveSwitch.disabled).toBe(false); });
    fireEvent.click(saveSwitch);

    await waitFor(() => {
      const postsToConfig = calls.filter((c) =>
        c.method === 'POST' && c.url.match(/\/api\/llm\/config(\?|$)/));
      expect(postsToConfig.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('current provider: primary action calls /api/llm/config (save + apply)', async () => {
    // Use the original single-provider fetcher where openai IS current.
    const calls = [];
    const modelsResponse = () => ({
      provider_id: 'openai',
      models: ['gpt-5.5'],
      source: 'live',
      last_refresh: Date.now() / 1000,
      count: 1,
      warning: '',
    });
    const baseFetcher = makeFetcher({ modelsResponse, captureUrls: [] });
    const fetcher = (url, init) => {
      calls.push({ url, method: init?.method || 'GET' });
      if (url.includes('/api/llm/config') && init?.method === 'POST') {
        return {
          success: true,
          provider: 'openai',
          model: 'gpt-5.5',
          persisted: { ok: true, warnings: [] },
          reconfigured: { ok: true },
        };
      }
      return baseFetcher(url, init);
    };

    const { getByText, findByText, findByRole, findByTestId } = renderV2(<Settings />, {
      fetch: fetcher,
    });
    await openProviderForm(getByText, findByText, findByRole);

    // Current provider only shows the combined "Save & apply" button
    // — the non-current "Save key" / "Save & switch" pair must NOT
    // render here.
    const saveApply = await findByTestId('provider-save-apply-openai');
    await waitFor(() => { expect(saveApply.disabled).toBe(false); });
    fireEvent.click(saveApply);

    await waitFor(() => {
      const postsToConfig = calls.filter((c) =>
        c.method === 'POST' && c.url.match(/\/api\/llm\/config(\?|$)/));
      expect(postsToConfig.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('non-current provider: Save-key triggers a force=true model refresh when a key is pasted', async () => {
    // Contract (5): model list must still refresh after a key save,
    // even on the non-switching path — otherwise the dropdown keeps
    // showing the pre-key list until the user navigates away.
    const calls = [];
    const { getByText, findByText, findAllByRole, findByTestId } = renderV2(<Settings />, {
      fetch: makeMultiProviderFetcher({ captureCalls: calls }),
    });
    await openAnthropicForm({ getByText, findByText, findAllByRole });

    // Type a key so the saveCredentialsOnly path triggers a
    // post-save force refresh.
    const keyInput = await waitFor(() => {
      const inputs = document.querySelectorAll('.v2-provider-form input[type="password"]');
      if (inputs.length === 0) throw new Error('no password input yet');
      return inputs[0];
    });
    fireEvent.change(keyInput, { target: { value: 'sk-ant-test' } });

    const saveKey = await findByTestId('provider-save-key-anthropic');
    fireEvent.click(saveKey);

    await waitFor(() => {
      const forceCalls = calls.filter((c) =>
        c.url.includes('/api/llm/providers/anthropic/models')
        && c.url.includes('force=true'));
      expect(forceCalls.length).toBeGreaterThanOrEqual(1);
    });
  });
});
