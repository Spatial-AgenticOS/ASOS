import React, { useCallback, useEffect, useState } from 'react';
import { Bluetooth, QrCode, KeyRound, Smartphone, Terminal, Copy, Check, RefreshCw } from 'lucide-react';
import Modal from '../ui/Modal';
import Tabs from '../ui/Tabs';
import DeviceQRCode from '../ui/DeviceQRCode';
import { apiFetch, apiJson } from '../lib/api';

/**
 * PairDeviceModal — four first-class pairing flows. No dead branches.
 *
 *   1) Web phone — generates a /pair?t=<TOKEN> URL + QR. Any phone
 *      camera scans it, lands on Pair.jsx, one tap = live browser_node.
 *      NO app install. This is the default tab.
 *   2) Daemon token — generates a pairing token + shows a copy-paste
 *      one-liner for the Python node SDK and the phone-bridge daemon.
 *      Vendors use this.
 *   3) QR (native app) — legacy host+port+token JSON for the iOS /
 *      Android app.
 *   4) Bluetooth — Web BLE for browser-level scanning (kept).
 */
export default function PairDeviceModal({ open, onClose, onPaired }) {
  const [tab, setTab] = useState('web_phone');
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Pair a device"
      size="md"
    >
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { id: 'web_phone', label: 'Web phone' },
          { id: 'daemon', label: 'Daemon token' },
          { id: 'app_qr', label: 'Native app QR' },
          { id: 'ble', label: 'Bluetooth' },
        ]}
      />
      <div className="v2-pair-body">
        {tab === 'web_phone' && <WebPhoneTab />}
        {tab === 'daemon' && <DaemonTokenTab onPaired={onPaired} />}
        {tab === 'app_qr' && <AppQRTab />}
        {tab === 'ble' && <BLETab onPaired={onPaired} />}
      </div>
    </Modal>
  );
}

function useCopy() {
  const [copied, setCopied] = useState(null);
  const copy = useCallback((id, text) => {
    try {
      navigator.clipboard.writeText(text);
      setCopied(id);
      setTimeout(() => setCopied((c) => (c === id ? null : c)), 1400);
    } catch { /* ignore */ }
  }, []);
  return [copied, copy];
}

function WebPhoneTab() {
  // Token issuance happens INSIDE the active tab so a user who only
  // wanted to peek at the modal (e.g. opened it from the dock) doesn't
  // leave behind a stray pairing row. The handshake-completion event
  // arrives over the WebSocket — `onPaired` is fired by the parent on
  // modal close so the Paired list refreshes either way.
  const [pair, setPair] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, copy] = useCopy();

  const generate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const body = await apiJson('/api/devices/pair/url?name=web-phone');
      setPair(body);
    } catch (err) {
      setError(err?.message || 'failed to generate token');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { generate(); }, [generate]);

  const url = pair?.url || '';

  return (
    <div className="v2-pair-phone-camera" data-testid="pair-web-phone">
      <div className="v2-p v2-p--muted" style={{ marginBottom: 10 }}>
        <Smartphone size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
        Open the phone's camera app, point it at this QR. A browser opens,
        they tap "Pair this device" once — phone becomes a real HUP node.
        No app install.
      </div>
      {busy && <div className="v2-chip v2-chip--warn">Generating one-time link…</div>}
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
      {url && (
        <>
          <div className="v2-pair-qr" style={{ display: 'flex', justifyContent: 'center', marginBottom: 10 }}>
            <DeviceQRCode size={240} value={url} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
            <code className="v2-p v2-p--tiny" style={{ flex: 1, wordBreak: 'break-all' }} data-testid="pair-web-phone-url">
              {url}
            </code>
            <button
              type="button"
              className="v2-btn v2-btn--ghost"
              onClick={() => copy('url', url)}
              aria-label="Copy URL"
            >
              {copied === 'url' ? <Check size={13} /> : <Copy size={13} />}
            </button>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={generate} aria-label="New token">
              <RefreshCw size={13} />
            </button>
          </div>
        </>
      )}
      <p className="v2-p v2-p--tiny v2-p--muted" style={{ marginTop: 10 }} data-testid="pair-web-phone-hint">
        Scan with your phone camera. Tap Pair when the page opens.
      </p>
      <p className="v2-p v2-p--tiny v2-p--muted" style={{ marginTop: 4 }}>
        Privacy: sensor streams start only after the user taps "Allow".
        Tab-hidden more than 60 s auto-pauses them. Closing the tab tears
        down the WebSocket.
      </p>
    </div>
  );
}

function DaemonTokenTab({ onPaired }) {
  const [pair, setPair] = useState(null);
  const [nodeId, setNodeId] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, copy] = useCopy();

  const generate = useCallback(async () => {
    if (!nodeId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch('/api/devices/pair', {
        method: 'POST',
        body: JSON.stringify({
          name: nodeId.trim(),
          kind: 'hup',
          node_id: nodeId.trim(),
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body?.error) {
        setError(body?.detail || body?.error || `${r.status}`);
        return;
      }
      setPair(body);
      if (onPaired) onPaired({ source: 'daemon', ...body });
    } catch (err) {
      setError(err?.message || 'failed');
    } finally {
      setBusy(false);
    }
  }, [nodeId, onPaired]);

  const brainUrl = typeof window !== 'undefined' ? window.location.origin : '';
  const wsUrl = brainUrl.replace(/^http/, 'ws') + '/v1/node';

  const pythonOneLiner = pair
    ? `pip install feral-node-sdk && python -m feral_node_sdk.cli --node-id "${pair.node_id || nodeId}" --brain-url "${wsUrl}" --token "${pair.token}"`
    : '';
  const bridgeOneLiner = pair
    ? `curl -fsSL ${brainUrl}/install-phone-bridge.sh | bash -s -- --token "${pair.token}" --brain-url "${wsUrl}"`
    : '';

  return (
    <div className="v2-pair-daemon">
      <div className="v2-p v2-p--muted" style={{ marginBottom: 10 }}>
        <KeyRound size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
        Issue a pairing token and drop a one-liner on any laptop / server.
        The token authenticates the next WebSocket that attaches with
        matching <code>node_id</code>.
      </div>
      <label className="v2-step-field">
        <span>Node ID (your choice — persists across reboots)</span>
        <input
          className="v2-input"
          value={nodeId}
          onChange={(e) => setNodeId(e.target.value)}
          placeholder="my-laptop-bridge"
        />
      </label>
      <button
        type="button"
        className="v2-btn v2-btn--primary"
        onClick={generate}
        disabled={busy || !nodeId.trim()}
        style={{ marginTop: 8 }}
      >
        {busy ? 'Issuing…' : 'Issue token'}
      </button>

      {error && <div className="v2-chip v2-chip--error" style={{ marginTop: 8 }}>{error}</div>}

      {pair && (
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="v2-chip v2-chip--live">Token issued — copy either one-liner below.</div>

          <OneLiner
            id="py"
            label="Python SDK (any OS)"
            cmd={pythonOneLiner}
            copied={copied === 'py'}
            onCopy={() => copy('py', pythonOneLiner)}
          />
          <OneLiner
            id="bridge"
            label="Phone-bridge daemon (Mac / Linux)"
            cmd={bridgeOneLiner}
            copied={copied === 'bridge'}
            onCopy={() => copy('bridge', bridgeOneLiner)}
          />

          <p className="v2-p v2-p--tiny v2-p--muted" style={{ marginTop: 4 }}>
            The token is only shown once. If you lose it, revoke + reissue.
          </p>
        </div>
      )}
    </div>
  );
}

function OneLiner({ id, label, cmd, copied, onCopy }) {
  return (
    <div className="v2-publish-cli" id={`one-${id}`}>
      <div className="v2-publish-cli-label">{label}</div>
      <div className="v2-publish-cli-row">
        <Terminal size={13} aria-hidden="true" />
        <code>{cmd}</code>
        <button type="button" className="v2-btn v2-btn--ghost" onClick={onCopy} aria-label="Copy command">
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  );
}

function AppQRTab() {
  return (
    <div className="v2-pair-qr">
      <DeviceQRCode size={240} mode="app" />
      <div className="v2-p v2-p--muted">
        <QrCode size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
        Scan from the FERAL iOS or Android app. The QR encodes
        <code> &#123;host, port, token&#125;</code> — the app connects to
        the Brain and registers as a real HUP node.
      </div>
    </div>
  );
}

function BLETab({ onPaired }) {
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const [device, setDevice] = useState(null);

  const supported = typeof navigator !== 'undefined' && 'bluetooth' in navigator;

  const scan = async () => {
    setError(null);
    setScanning(true);
    try {
      const dev = await navigator.bluetooth.requestDevice({
        acceptAllDevices: true,
        optionalServices: ['battery_service', 'heart_rate', 'device_information'],
      });
      setDevice(dev);
      if (onPaired) onPaired({ source: 'ble', id: dev.id, name: dev.name });
    } catch (err) {
      if (err.name !== 'NotFoundError') setError(err.message);
    } finally {
      setScanning(false);
    }
  };

  if (!supported) {
    return (
      <div className="v2-p v2-p--muted">
        <Bluetooth size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
        Web Bluetooth isn't available in this browser. Use Chrome / Edge
        on a machine with a BLE radio, or use the desktop app for
        production BLE scanning.
      </div>
    );
  }

  return (
    <div className="v2-pair-ble">
      <button type="button" className="v2-btn v2-btn--primary" onClick={scan} disabled={scanning}>
        {scanning ? 'Scanning…' : 'Start BLE scan'}
      </button>
      {device && (
        <div className="v2-pair-picked">
          <strong>{device.name || device.id}</strong>
          <span className="v2-p v2-p--muted">
            Browser-level BLE pairs to this page only. For ongoing device control, run a HUP daemon and enter its token.
          </span>
        </div>
      )}
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </div>
  );
}
