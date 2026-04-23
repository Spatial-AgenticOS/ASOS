import { describe, it, expect } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Setup from '../../pages/Setup';


describe('Setup (new v2 wizard)', () => {
  it('renders the step tabs on mount', async () => {
    const { getAllByRole, container } = renderV2(<Setup />, {
      fetch: (url) => {
        if (url.includes('/api/llm/providers')) return { providers: [], count: 0 };
        if (url.includes('/api/llm/config')) return { provider: '', model: '' };
        if (url.includes('/api/audio/providers')) return { stt: [], tts: [] };
        if (url.includes('/api/audio/config')) {
          return { stt_provider: 'openai', stt_model: 'whisper-1', tts_provider: 'openai', tts_model: 'tts-1', tts_voice: 'nova' };
        }
        return {};
      },
    });
    // Tabs render as role="tab"
    await waitFor(() => {
      const tabs = getAllByRole('tab');
      expect(tabs.length).toBeGreaterThanOrEqual(5);
    });
    expect(container.querySelector('[data-testid="v2-marker"]')).toBeTruthy();
  });

  it('renders providers once the API responds', async () => {
    const { findByTestId } = renderV2(<Setup />, {
      fetch: (url) => {
        if (url.includes('/api/llm/providers') && !url.includes('/models')) {
          return {
            providers: [
              {
                id: 'openai', display_name: 'OpenAI', supports_local: false,
                requires_api_key: true, configured: false, reachable: false,
                default_base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o-mini',
                credential_env_var: 'OPENAI_API_KEY', aliases: ['open ai'], notes: '',
                last_refresh: 0, error: '',
              },
              {
                id: 'ollama', display_name: 'Ollama (local)', supports_local: true,
                requires_api_key: false, configured: true, reachable: true,
                default_base_url: 'http://localhost:11434', default_model: 'llama3.3',
                credential_env_var: '', aliases: [], notes: '',
                last_refresh: 0, error: '',
              },
            ],
            count: 2,
          };
        }
        if (url.includes('/models')) return { models: [], source: 'fallback' };
        return {};
      },
    });
    // Navigate to the LLM step
    const tabButtons = document.querySelectorAll('[role="tab"]');
    // Second tab is "LLM provider"
    tabButtons[1]?.click();
    expect(await findByTestId('v2-setup-pick-openai')).toBeInTheDocument();
    expect(await findByTestId('v2-setup-pick-ollama')).toBeInTheDocument();
  });

  it('has a Continue button', async () => {
    const { findByTestId } = renderV2(<Setup />, {
      fetch: () => ({}),
    });
    expect(await findByTestId('v2-setup-next')).toBeInTheDocument();
  });
});
