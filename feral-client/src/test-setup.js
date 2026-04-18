import '@testing-library/jest-dom'

// jsdom ships with a localStorage prototype but vitest's environment=jsdom
// sometimes loses it when tests replace `navigator` or run in isolate mode.
// Install a simple in-memory fallback so module-level code that reads from
// localStorage at import time (for example GlassBrain.jsx reading a cached
// API key) doesn't crash at collection time.
if (typeof window !== 'undefined') {
  const ensureStorage = (key) => {
    const current = window[key];
    if (!current || typeof current.getItem !== 'function') {
      const store = new Map();
      const shim = {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, String(v)),
        removeItem: (k) => store.delete(k),
        clear: () => store.clear(),
        key: (i) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      };
      Object.defineProperty(window, key, { configurable: true, value: shim });
      Object.defineProperty(globalThis, key, { configurable: true, value: shim });
    }
  };
  ensureStorage('localStorage');
  ensureStorage('sessionStorage');
}
