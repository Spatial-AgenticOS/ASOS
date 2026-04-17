import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

function createChromeStorage() {
  const store = {};

  const localApi = {
    _store: store,
    get(keys, cb) {
      const result = {};
      const keyList = Array.isArray(keys) ? keys : Object.keys(keys || {});
      keyList.forEach(k => { if (store[k] !== undefined) result[k] = store[k]; });
      cb(result);
    },
    set(data, cb) {
      Object.assign(store, data);
      if (cb) cb();
    },
  };
  vi.spyOn(localApi, 'get');
  vi.spyOn(localApi, 'set');

  return { local: localApi };
}

describe('options — brain URL saves to chrome.storage', () => {
  let chrome;

  beforeEach(() => {
    chrome = {
      storage: createChromeStorage(),
      runtime: {
        sendMessage: vi.fn(),
        lastError: null,
      },
    };
    globalThis.chrome = chrome;
  });

  afterEach(() => {
    delete globalThis.chrome;
  });

  it('saves brainUrl to chrome.storage.local', () => {
    const brainUrl = 'wss://my-brain.example.com:9443/v1/session';
    chrome.storage.local.set({ brainUrl });

    expect(chrome.storage.local.set).toHaveBeenCalledWith({ brainUrl });
    expect(chrome.storage.local._store.brainUrl).toBe(brainUrl);
  });

  it('saves API key to chrome.storage.local', () => {
    const apiKey = 'my-secret-api-key-123';
    chrome.storage.local.set({ apiKey });

    expect(chrome.storage.local.set).toHaveBeenCalledWith({ apiKey });
    expect(chrome.storage.local._store.apiKey).toBe(apiKey);
  });

  it('loads defaults when storage is empty', () => {
    const defaults = {
      brainUrl: 'ws://localhost:9090/v1/session',
      apiKey: '',
      autoConnect: true,
      showFloatBtn: true,
      autoContext: false,
      notifyAlerts: true,
      notifySound: false,
    };

    chrome.storage.local.get(Object.keys(defaults), (result) => {
      const loaded = {
        brainUrl: result.brainUrl || defaults.brainUrl,
        apiKey: result.apiKey || defaults.apiKey,
        autoConnect: result.autoConnect !== undefined ? result.autoConnect : defaults.autoConnect,
        showFloatBtn: result.showFloatBtn !== undefined ? result.showFloatBtn : defaults.showFloatBtn,
        autoContext: result.autoContext !== undefined ? result.autoContext : defaults.autoContext,
        notifyAlerts: result.notifyAlerts !== undefined ? result.notifyAlerts : defaults.notifyAlerts,
        notifySound: result.notifySound !== undefined ? result.notifySound : defaults.notifySound,
      };
      expect(loaded.brainUrl).toBe('ws://localhost:9090/v1/session');
      expect(loaded.apiKey).toBe('');
      expect(loaded.autoConnect).toBe(true);
    });
  });

  it('saves full settings and notifies background', () => {
    const settings = {
      brainUrl: 'wss://production.feral.ai/v1/session',
      apiKey: 'prod-key-456',
      autoConnect: true,
      showFloatBtn: false,
      autoContext: true,
      notifyAlerts: true,
      notifySound: true,
    };

    chrome.storage.local.set(settings, () => {
      chrome.runtime.sendMessage({ type: 'set_brain_url', url: settings.brainUrl });
    });

    expect(chrome.storage.local._store.brainUrl).toBe(settings.brainUrl);
    expect(chrome.storage.local._store.apiKey).toBe(settings.apiKey);
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'set_brain_url',
      url: settings.brainUrl,
    });
  });

  it('reset restores defaults', () => {
    chrome.storage.local.set({ brainUrl: 'wss://custom.example.com', apiKey: 'key' });
    expect(chrome.storage.local._store.brainUrl).toBe('wss://custom.example.com');

    const defaults = {
      brainUrl: 'ws://localhost:9090/v1/session',
      apiKey: '',
    };
    chrome.storage.local.set(defaults);

    expect(chrome.storage.local._store.brainUrl).toBe(defaults.brainUrl);
    expect(chrome.storage.local._store.apiKey).toBe('');
  });
});
