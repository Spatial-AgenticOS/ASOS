/**
 * Devices page — pair flow + paired list.
 *
 * Bugs we guard against:
 *
 *   1. "+ Pair new device" used to silently create a pairing token
 *      without ever opening the modal. The modal must open, default to
 *      the Web phone tab, and the paired list must refresh on close.
 *
 *   2. Token issuance must be explicit. Opening the modal should NOT
 *      mint a backend row; only clicking "Generate one-time link"
 *      does.
 *
 *   3. If a generated token is never claimed, closing the modal must
 *      revoke it so no phantom row remains.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';
import Devices from '../../pages/Devices';

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn(async () => 'data:image/png;base64,mock'),
  },
}));

beforeEach(() => {
  if (!navigator.clipboard) {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn() },
      configurable: true,
    });
  }
});

function makeDevicesResponder({ onCall, pairedRows } = {}) {
  return (url, init) => {
    if (onCall) onCall(url, init);
    if (url.includes('/api/devices/connected')) return { devices: [] };
    if (url.includes('/api/devices/paired')) return { devices: pairedRows || [] };
    if (url.includes('/api/hardware/mesh')) return { nodes: [] };
    if (url.includes('/api/devices/pair/url')) {
      return {
        token: 'tok-12345',
        device_id: 'dev-12345',
        url: 'http://localhost:9090/pair?t=tok-12345',
      };
    }
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

  it('does not mint a token until "Generate one-time link" is clicked', async () => {
    const issued = [];
    const responder = makeDevicesResponder({
      onCall: (url) => {
        if (url.includes('/api/devices/pair/url')) issued.push(url);
      },
    });
    const { getByRole, findByRole, getByTestId } = renderV2(<Devices />, { fetch: responder });

    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    await findByRole('dialog', { name: /Pair a device/i });
    expect(issued.length).toBe(0);
    fireEvent.click(getByTestId('pair-web-phone-generate'));
    await findByRole('img', { name: /Web phone pairing QR code/i });
    expect(issued.length).toBe(1);
  });

  it('switching tabs does not mint extra web-phone tokens', async () => {
    const issued = [];
    const responder = makeDevicesResponder({
      onCall: (url) => {
        if (url.includes('/api/devices/pair/url')) issued.push(url);
      },
    });
    const { getByRole, findByRole, getByTestId } = renderV2(<Devices />, { fetch: responder });

    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    await findByRole('dialog', { name: /Pair a device/i });
    fireEvent.click(getByTestId('pair-web-phone-generate'));
    await findByRole('img', { name: /Web phone pairing QR code/i });
    expect(issued.length).toBe(1);

    fireEvent.click(getByRole('tab', { name: /Daemon token/i }));
    fireEvent.click(getByRole('tab', { name: /Web phone/i }));
    expect(issued.length).toBe(1);
  });

  it('shows a one-time PIN when generated with default settings', async () => {
    const responder = (url) => {
      if (url.includes('/api/devices/connected')) return { devices: [] };
      if (url.includes('/api/devices/paired')) return { devices: [] };
      if (url.includes('/api/hardware/mesh')) return { nodes: [] };
      if (url.includes('/api/devices/pair/url')) {
        return {
          token: 'tok-pin',
          device_id: 'dev-pin',
          url: 'http://localhost:9090/pair?t=tok-pin',
          pin_required: true,
          pin: '2299',
        };
      }
      return {};
    };
    const { getByRole, findByRole, getByTestId } = renderV2(<Devices />, { fetch: responder });

    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    await findByRole('dialog', { name: /Pair a device/i });
    fireEvent.click(getByTestId('pair-web-phone-generate'));
    expect(await findByRole('img', { name: /Web phone pairing QR code/i })).toBeInTheDocument();
    expect(getByTestId('pair-web-phone-pin')).toHaveTextContent('2299');
  });

  it('native app tab does not mint until explicit generate click', async () => {
    const qrCalls = [];
    const responder = (url) => {
      if (url.includes('/api/devices/connected')) return { devices: [] };
      if (url.includes('/api/devices/paired')) return { devices: [] };
      if (url.includes('/api/hardware/mesh')) return { nodes: [] };
      if (url.includes('/api/devices/pair/qr')) {
        qrCalls.push(url);
      }
      return {};
    };
    const { getByRole, findByRole, getByTestId } = renderV2(<Devices />, { fetch: responder });

    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    await findByRole('dialog', { name: /Pair a device/i });
    fireEvent.click(getByRole('tab', { name: /Native app QR/i }));
    expect(qrCalls.length).toBe(0);
    fireEvent.click(getByTestId('pair-app-qr-generate'));
    await waitFor(() => expect(qrCalls.length).toBe(1));
  });

  it('revokes the unclaimed Web-phone token when the modal closes (no phantom row)', async () => {
    const deletes = [];
    const responder = (url, init) => {
      if ((init?.method || 'GET') === 'DELETE' && url.match(/\/api\/devices\/[^/]+$/)) {
        deletes.push(url);
        return {};
      }
      if (url.includes('/api/devices/connected')) return { devices: [] };
      if (url.includes('/api/devices/paired')) {
        // Brain reports the issued token as still unclaimed.
        return { devices: [{ device_id: 'dev-12345', name: 'web-phone', claimed_at: null }] };
      }
      if (url.includes('/api/hardware/mesh')) return { nodes: [] };
      if (url.includes('/api/devices/pair/url')) {
        return {
          token: 'tok-12345',
          device_id: 'dev-12345',
          url: 'http://localhost:9090/pair?t=tok-12345',
        };
      }
      return {};
    };

    const { getByRole, findByRole, getByTestId, getAllByRole } = renderV2(<Devices />, {
      fetch: responder,
    });

    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    await findByRole('dialog', { name: /Pair a device/i });
    fireEvent.click(getByTestId('pair-web-phone-generate'));
    // Wait for issuance + QR rendering so the device_id is tracked.
    await findByRole('img', { name: /Web phone pairing QR code/i });

    fireEvent.click(getAllByRole('button', { name: /Close/i })[0]);

    await waitFor(() => {
      expect(deletes.some((u) => u.endsWith('/api/devices/dev-12345'))).toBe(true);
    });
  });

  it('keeps a CLAIMED Web-phone token (does not revoke a successful pairing)', async () => {
    const deletes = [];
    const responder = (url, init) => {
      if ((init?.method || 'GET') === 'DELETE' && url.match(/\/api\/devices\/[^/]+$/)) {
        deletes.push(url);
        return {};
      }
      if (url.includes('/api/devices/connected')) return { devices: [] };
      if (url.includes('/api/devices/paired')) {
        // Brain reports the issued token as already claimed by the
        // phone that scanned the QR — the modal MUST keep it.
        return { devices: [{ device_id: 'dev-12345', name: 'web-phone', claimed_at: 1714000000 }] };
      }
      if (url.includes('/api/hardware/mesh')) return { nodes: [] };
      if (url.includes('/api/devices/pair/url')) {
        return {
          token: 'tok-12345',
          device_id: 'dev-12345',
          url: 'http://localhost:9090/pair?t=tok-12345',
        };
      }
      return {};
    };

    const { getByRole, findByRole, getByTestId, getAllByRole } = renderV2(<Devices />, {
      fetch: responder,
    });

    fireEvent.click(getByRole('button', { name: /Pair new device/i }));
    await findByRole('dialog', { name: /Pair a device/i });
    fireEvent.click(getByTestId('pair-web-phone-generate'));
    await findByRole('img', { name: /Web phone pairing QR code/i });

    fireEvent.click(getAllByRole('button', { name: /Close/i })[0]);

    // Drain microtasks; if a delete is going to fire it does so by now.
    await new Promise((r) => setTimeout(r, 30));
    expect(deletes.some((u) => u.endsWith('/api/devices/dev-12345'))).toBe(false);
  });
});
