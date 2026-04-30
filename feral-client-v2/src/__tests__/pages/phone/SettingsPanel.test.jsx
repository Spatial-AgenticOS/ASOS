import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor, act } from '@testing-library/react';
import SettingsPanel from '../../../pages/phone/SettingsPanel';

function installFetchMock(responder) {
  const resolveBody = typeof responder === 'function' ? responder : () => ({});
  vi.stubGlobal('fetch', vi.fn((input, init) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    const body = resolveBody(url, init) ?? {};
    return Promise.resolve({
      ok: true, status: 200, statusText: 'OK',
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(JSON.stringify(body)),
      headers: new Map(),
    });
  }));
}

const defaultConfig = {
  voice: {
    mode: 'openai_realtime',
    realtime: { openai_voice: 'marin', gemini_model: 'gemini-2.0-flash-exp' },
    chained: { stt_provider: 'deepgram', stt_model: 'nova-3', tts_provider: 'openai', tts_voice: 'alloy' },
  },
};

async function renderSettings(config = defaultConfig) {
  installFetchMock((url) => {
    if (url.includes('/api/config')) return config;
    return {};
  });
  let result;
  await act(async () => {
    result = render(<SettingsPanel initialConfig={config} />);
  });
  return result;
}

describe('SettingsPanel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the voice section with mode picker', async () => {
    const { getByTestId } = await renderSettings();
    expect(getByTestId('voice-section')).toBeTruthy();
    expect(getByTestId('mode-picker')).toBeTruthy();
  });

  it('renders current config — openai_realtime active', async () => {
    const { getByTestId } = await renderSettings();
    const btn = getByTestId('mode-openai_realtime');
    expect(btn.getAttribute('aria-checked')).toBe('true');
  });

  it('selecting chained reveals sub-pickers', async () => {
    const { getByTestId, queryByTestId } = await renderSettings();
    expect(queryByTestId('chained-sub')).toBeNull();
    await act(async () => { fireEvent.click(getByTestId('mode-chained')); });
    expect(getByTestId('chained-sub')).toBeTruthy();
    expect(getByTestId('stt-provider-picker')).toBeTruthy();
    expect(getByTestId('tts-provider-picker')).toBeTruthy();
  });

  it('openai_realtime mode shows voice picker', async () => {
    const { getByTestId, queryByTestId } = await renderSettings();
    expect(getByTestId('openai-sub')).toBeTruthy();
    expect(getByTestId('openai-voice-picker')).toBeTruthy();
    expect(queryByTestId('chained-sub')).toBeNull();
  });

  it('gemini_live mode shows model picker', async () => {
    const geminiConfig = { ...defaultConfig, voice: { ...defaultConfig.voice, mode: 'gemini_live' } };
    const { getByTestId } = await renderSettings(geminiConfig);
    expect(getByTestId('gemini-sub')).toBeTruthy();
    expect(getByTestId('gemini-model-picker')).toBeTruthy();
  });

  it('debounced write fires after 300ms on mode change', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { getByTestId } = await renderSettings();
    await act(async () => { fireEvent.click(getByTestId('mode-chained')); });
    await act(async () => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();
    await waitFor(() => {
      const patchCall = fetch.mock.calls.find(
        ([url, init]) => url.includes('/api/config') && (init?.method === 'PATCH' || init?.method === 'POST')
      );
      expect(patchCall).toBeTruthy();
    });
  });

  it('"Saved" indicator shows after successful write', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { getByTestId, queryByTestId } = await renderSettings();
    expect(queryByTestId('saved-indicator')).toBeNull();
    await act(async () => { fireEvent.click(getByTestId('mode-chained')); });
    await act(async () => { vi.advanceTimersByTime(350); });
    vi.useRealTimers();
    await waitFor(() => { expect(queryByTestId('saved-indicator')).toBeTruthy(); });
  });

  it('changing STT provider updates STT model to provider default', async () => {
    const chainedConfig = { ...defaultConfig, voice: { ...defaultConfig.voice, mode: 'chained' } };
    const { getByTestId } = await renderSettings(chainedConfig);
    await act(async () => {
      fireEvent.change(getByTestId('stt-provider-picker'), { target: { value: 'openai_whisper' } });
    });
    expect(getByTestId('stt-model-picker').value).toBe('whisper-1');
  });

  it('changing TTS provider updates TTS voice to provider default', async () => {
    const chainedConfig = { ...defaultConfig, voice: { ...defaultConfig.voice, mode: 'chained' } };
    const { getByTestId } = await renderSettings(chainedConfig);
    await act(async () => {
      fireEvent.change(getByTestId('tts-provider-picker'), { target: { value: 'elevenlabs' } });
    });
    expect(getByTestId('tts-voice-picker').value).toBe('rachel');
  });
});
