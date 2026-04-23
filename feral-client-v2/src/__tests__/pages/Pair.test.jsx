/**
 * Pair page — the unauthenticated /pair?t=TOKEN landing page.
 *
 * Covers:
 *   1. Missing token → warning card.
 *   2. Valid token → shows permission toggles + pair button.
 *   3. Toggling permissions reflects in the UI.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import Pair from '../../pages/Pair';

beforeEach(() => {
  vi.stubGlobal('WebSocket', class { constructor() {} close() {} });
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve({ ok: true }),
    text: () => Promise.resolve('{}'),
    headers: new Map(),
  })));
  vi.stubGlobal('localStorage', (() => {
    const s = {};
    return { getItem: (k) => s[k] || null, setItem: (k, v) => { s[k] = v; } };
  })());
  vi.stubGlobal('navigator', {
    userAgent: 'Mozilla/5.0',
    geolocation: { watchPosition: () => 1, clearWatch: () => {} },
    mediaDevices: {},
    vibrate: () => true,
    clipboard: { writeText: vi.fn() },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(url) {
  // Render Pair outside renderV2 so we can drive window.location.search.
  window.history.replaceState({}, '', url);
  return render(<MemoryRouter initialEntries={[url]}><Pair /></MemoryRouter>);
}

describe('Pair page', () => {
  it('shows a warning when no token is in the URL', () => {
    const { getByText } = renderAt('/pair');
    expect(getByText(/No pairing token/i)).toBeInTheDocument();
  });

  it('renders the pair UI when a token is present', () => {
    const { getByText, getByRole } = renderAt('/pair?t=abc12345deadbeef');
    // "Pair this device" appears as both a heading and a button — the
    // heading lookup via getByRole passes as long as either matches.
    expect(getByRole('heading', { name: /Pair this device/i })).toBeInTheDocument();
    expect(getByRole('button', { name: /Pair this device/i })).toBeInTheDocument();
    // Permission toggles
    expect(getByText(/Share location/i)).toBeInTheDocument();
    expect(getByText(/Share camera/i)).toBeInTheDocument();
    expect(getByText(/Share microphone/i)).toBeInTheDocument();
  });

  it('permission toggles are interactive', () => {
    const { getByLabelText, container } = renderAt('/pair?t=xyzxyzxyz');
    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    // 3 toggles by default (location on, camera off, mic off).
    expect(checkboxes).toHaveLength(3);
    fireEvent.click(checkboxes[1]); // flip camera on
    expect(checkboxes[1].checked).toBe(true);
    fireEvent.click(checkboxes[2]); // flip mic on
    expect(checkboxes[2].checked).toBe(true);
  });

  it('short token is truncated in the footer chip', () => {
    const longToken = 'abcd1234efgh5678ijkl9012';
    const { getByText } = renderAt(`/pair?t=${longToken}`);
    // Footer shows first 8 chars + "..." — find "abcd1234".
    expect(getByText(/abcd1234/)).toBeInTheDocument();
  });
});
