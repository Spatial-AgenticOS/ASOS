import { useCallback, useEffect, useState } from 'react';

/**
 * useTheme — single source of truth for the v2 light/dark theme.
 *
 * Reads from ``localStorage.feral_ui_theme``. Applies one of the two
 * classes (``v2-light`` / ``v2-dark``) to <html>. Emits a
 * ``feral_theme_change`` event so any other tab or listener can react.
 */
const STORAGE_KEY = 'feral_ui_theme';
const EVENT_NAME = 'feral_theme_change';

function readTheme() {
  if (typeof localStorage === 'undefined') return 'light';
  try {
    const pref = localStorage.getItem(STORAGE_KEY);
    if (pref === 'dark' || pref === 'light') return pref;
  } catch { /* silent */ }
  return 'light';
}

function applyTheme(theme) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('v2-light', theme === 'light');
  root.classList.toggle('v2-dark', theme === 'dark');
}

export function useTheme() {
  const [theme, setThemeState] = useState(readTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const onChange = () => setThemeState(readTheme());
    window.addEventListener(EVENT_NAME, onChange);
    window.addEventListener('storage', onChange);
    return () => {
      window.removeEventListener(EVENT_NAME, onChange);
      window.removeEventListener('storage', onChange);
    };
  }, []);

  const setTheme = useCallback((next) => {
    if (next !== 'light' && next !== 'dark') return;
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* silent */ }
    setThemeState(next);
    window.dispatchEvent(new CustomEvent(EVENT_NAME));
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  }, [theme, setTheme]);

  return { theme, setTheme, toggle };
}
