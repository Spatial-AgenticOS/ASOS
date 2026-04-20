import '@testing-library/jest-dom';

// jsdom sometimes loses the localStorage prototype when tests replace
// `navigator`. Install a small in-memory shim so module-level reads don't
// crash at collection time.
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

// Polyfills some pages expect.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (q) => ({
    matches: false,
    media: q,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}

if (typeof global !== 'undefined' && !global.IntersectionObserver) {
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
  };
}

if (typeof global !== 'undefined' && !global.ResizeObserver) {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
