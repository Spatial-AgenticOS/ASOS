import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import Apps from '../../pages/Apps';

describe('Apps launcher', () => {
  it('shows empty state when no apps are installed', async () => {
    const { findByText } = renderV2(<Apps />, {
      fetch: (url) => {
        if (url.includes('/api/apps')) return { count: 0, apps: [] };
        return {};
      },
    });
    expect(await findByText(/No apps installed yet/i)).toBeInTheDocument();
  });

  it('lists installed apps with an Open button per tile', async () => {
    const apps = [
      {
        app_id: 'feral-messages',
        version: '1.0.0',
        author: 'demo',
        description: 'A tiny messaging app',
        brand: { name: 'Messages', primary_color: '#22C55E' },
      },
      {
        app_id: 'feral-rides',
        version: '0.9.0',
        author: 'demo',
        description: 'A ride request flow',
        brand: { name: 'Rides', primary_color: '#2563EB' },
      },
    ];
    const { findByTestId } = renderV2(<Apps />, {
      fetch: (url) => {
        if (url.includes('/api/apps')) return { count: apps.length, apps };
        return {};
      },
    });
    expect(await findByTestId('v2-apps-open-feral-messages')).toBeInTheDocument();
    expect(await findByTestId('v2-apps-open-feral-rides')).toBeInTheDocument();
  });
});
