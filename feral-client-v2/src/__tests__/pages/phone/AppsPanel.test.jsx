import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { renderV2 } from '../../_helpers/renderV2';
import AppsPanel from '../../../pages/phone/AppsPanel';

function TestRoutes({ shell }) {
  return (
    <Routes>
      <Route path="/pair/:device_id/apps/:app_id" element={<AppsPanel shell={shell} />} />
    </Routes>
  );
}

describe('AppsPanel', () => {
  it('applies sdui_patch frames to the active phone surface', async () => {
    let onFrame = () => {};
    const shell = {
      subscribeFrame: vi.fn((handler) => {
        onFrame = handler;
        return () => {};
      }),
      sendFrame: vi.fn(),
    };

    const { findByText, queryByText } = renderV2(<TestRoutes shell={shell} />, {
      route: '/pair/phone-1/apps/demo-app',
    });

    act(() => {
      onFrame({
        type: 'genui_push',
        payload: {
          kind: 'interactive',
          app_id: 'demo-app',
          surface_id: 'home',
          screen_id: 'demo-app:home:phone-1',
          root: { type: 'VStack', children: [{ type: 'Text', value: 'before patch' }] },
        },
      });
    });

    expect(await findByText('before patch')).toBeInTheDocument();

    act(() => {
      onFrame({
        type: 'sdui_patch',
        payload: {
          screen_id: 'demo-app:home:phone-1',
          patches: [{ op: 'replace', path: '/children/0/value', value: 'after patch' }],
        },
      });
    });

    expect(await findByText('after patch')).toBeInTheDocument();
    expect(queryByText('before patch')).not.toBeInTheDocument();
  });
});
