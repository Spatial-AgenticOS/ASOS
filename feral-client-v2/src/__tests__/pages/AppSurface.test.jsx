import { describe, it, expect, beforeEach, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { renderV2 } from '../_helpers/renderV2';

let socketListener = null;
const fakeSocket = {
  subscribe: vi.fn((fn) => {
    socketListener = fn;
    return () => {};
  }),
  send: vi.fn(),
  connect: vi.fn(),
};

vi.mock('../../hooks/useFeralSocket', async () => {
  const actual = await vi.importActual('../../hooks/useFeralSocket');
  return {
    ...actual,
    useFeralSocket: () => fakeSocket,
  };
});

import AppSurface from '../../pages/AppSurface';

function TestRoutes() {
  return (
    <Routes>
      <Route path="/apps/:app_id" element={<AppSurface />} />
    </Routes>
  );
}

describe('AppSurface', () => {
  beforeEach(() => {
    socketListener = null;
    fakeSocket.subscribe.mockClear();
  });

  it('fetches the manifest + opens the entry surface + renders the tree inside a sandboxed iframe', async () => {
    const manifest = {
      app_id: 'demo-app',
      version: '1.0.0',
      brand: { name: 'Demo' },
      entry_surface_id: 'home',
      surfaces: [
        { surface_id: 'home', title: 'Home' },
        { surface_id: 'thread', title: 'Thread' },
      ],
    };
    const surfaceOpen = {
      success: true,
      app_id: 'demo-app',
      surface_id: 'home',
      screen_id: 'demo-app:home:v2-user',
      root: { type: 'VStack', children: [{ type: 'Text', value: 'welcome' }] },
    };
    const { findByTestId } = renderV2(<TestRoutes />, {
      route: '/apps/demo-app',
      fetch: (url) => {
        if (url.includes('/api/apps/demo-app/manifest')) {
          return { app_id: 'demo-app', manifest };
        }
        if (url.includes('/api/apps/demo-app/open')) {
          return surfaceOpen;
        }
        return {};
      },
    });
    const iframe = await findByTestId('v2-appsurface-iframe');
    expect(iframe).toBeInTheDocument();
    expect(iframe.getAttribute('sandbox')).toBe('allow-scripts');
    const srcDoc = iframe.getAttribute('srcdoc') || '';
    expect(srcDoc).toContain('welcome');
    expect(await findByTestId('v2-appsurface-tab-home')).toBeInTheDocument();
    expect(await findByTestId('v2-appsurface-tab-thread')).toBeInTheDocument();
  });

  it('applies sdui_patch frames to the active surface tree', async () => {
    const manifest = {
      app_id: 'demo-app',
      version: '1.0.0',
      brand: { name: 'Demo' },
      entry_surface_id: 'home',
      surfaces: [{ surface_id: 'home', title: 'Home' }],
    };
    const surfaceOpen = {
      success: true,
      app_id: 'demo-app',
      surface_id: 'home',
      screen_id: 'demo-app:home:v2-user',
      root: { type: 'VStack', children: [{ type: 'Text', value: 'before patch' }] },
    };
    const { findByTestId } = renderV2(<TestRoutes />, {
      route: '/apps/demo-app',
      fetch: (url) => {
        if (url.includes('/api/apps/demo-app/manifest')) return { app_id: 'demo-app', manifest };
        if (url.includes('/api/apps/demo-app/open')) return surfaceOpen;
        return {};
      },
    });

    const iframe = await findByTestId('v2-appsurface-iframe');
    expect(iframe.getAttribute('srcdoc') || '').toContain('before patch');
    expect(fakeSocket.subscribe).toHaveBeenCalled();

    socketListener?.({
      type: 'sdui_patch',
      payload: {
        screen_id: 'demo-app:home:v2-user',
        patches: [{ op: 'replace', path: '/children/0/value', value: 'after patch' }],
      },
    });

    await waitFor(() => {
      expect(iframe.getAttribute('srcdoc') || '').toContain('after patch');
    });
  });
});
