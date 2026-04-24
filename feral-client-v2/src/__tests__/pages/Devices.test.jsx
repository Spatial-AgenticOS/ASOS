/**
 * Devices page — pair flow + paired list.
 *
 * The bug we are guarding against: clicking "+ Pair new device" used to
 * silently create a pairing token without ever opening the modal. The
 * modal must open, default to the Web phone tab, and the paired list
 * must refresh when the modal closes.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Devices from '../../pages/Devices';

beforeEach(() => {
  if (!navigator.clipboard) {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn() },
      configurable: true,
    });
  }
});

function makeDevicesResponder({ onCall } = {}) {
  return (url, init) => {
    if (onCall) onCall(url, init);
    if (url.includes('/api/devices/connected')) return { devices: [] };
    if (url.includes('/api/devices/paired')) return { devices: [] };
    if (url.includes('/api/hardware/mesh')) return { nodes: [] };
    if (url.includes('/api/devices/pair/url')) return { token: 'tok-12345', url: 'http://localhost:9090/pair?t=tok-12345' };
    return {};
  };
}

describe('Devices', () => {
  it('renders the Devices pane heading', () => {
    const { getByRole } = renderV2(<Devices />, {
      fetch: makeDevicesResponder(),
    });
    expect(getByRole('heading', { name: /Devices/i })).toBeInTheDocument();
  });

  it('opens the PairDeviceModal when "+ Pair new device" is clicked', async () => {
    const { getByRole, findByRole } = renderV2(<Devices />, {
      fetch: makeDevicesResponder(),
    });
    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    expect(await findByRole('dialog', { name: /Pair a device/i })).toBeInTheDocument();
  });

  it('defaults the modal to the Web phone tab', async () => {
    const { getByRole, findByRole } = renderV2(<Devices />, {
      fetch: makeDevicesResponder(),
    });
    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    const webPhoneTab = await findByRole('tab', { name: /Web phone/i });
    expect(webPhoneTab).toHaveAttribute('aria-selected', 'true');
    const daemonTab = getByRole('tab', { name: /Daemon token/i });
    expect(daemonTab).toHaveAttribute('aria-selected', 'false');
  });

  it('switching to the Daemon token tab shows the install one-liner UI', async () => {
    const { getByRole, findByRole, findByPlaceholderText } = renderV2(<Devices />, {
      fetch: makeDevicesResponder(),
    });
    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    const daemonTab = await findByRole('tab', { name: /Daemon token/i });
    fireEvent.click(daemonTab);
    expect(await findByPlaceholderText(/my-laptop-bridge/i)).toBeInTheDocument();
    expect(getByRole('button', { name: /Issue token/i })).toBeInTheDocument();
  });

  it('closing the modal triggers a refresh of the Paired list', async () => {
    const calls = [];
    const responder = makeDevicesResponder({
      onCall: (url) => {
        if (url.includes('/api/devices/paired')) calls.push(url);
      },
    });
    const { getByRole, findByRole, getAllByRole } = renderV2(<Devices />, {
      fetch: responder,
    });

    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    const beforeOpen = calls.length;

    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    await findByRole('dialog', { name: /Pair a device/i });

    const closeBtns = getAllByRole('button', { name: /Close/i });
    fireEvent.click(closeBtns[0]);

    await waitFor(() => expect(calls.length).toBeGreaterThan(beforeOpen));
  });
});
