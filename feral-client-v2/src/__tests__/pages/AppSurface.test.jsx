import { describe, it, expect } from 'vitest';
import { Routes, Route } from 'react-router-dom';
import { renderV2 } from '../_helpers/renderV2';
import AppSurface from '../../pages/AppSurface';

function TestRoutes() {
  return (
    <Routes>
      <Route path="/apps/:app_id" element={<AppSurface />} />
    </Routes>
  );
}

describe('AppSurface', () => {
  it('fetches the manifest + opens the entry surface + renders the tree', async () => {
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
    const { findByTestId, findByText } = renderV2(<TestRoutes />, {
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
    expect(await findByText('welcome')).toBeInTheDocument();
    expect(await findByTestId('v2-appsurface-tab-home')).toBeInTheDocument();
    expect(await findByTestId('v2-appsurface-tab-thread')).toBeInTheDocument();
  });
});
