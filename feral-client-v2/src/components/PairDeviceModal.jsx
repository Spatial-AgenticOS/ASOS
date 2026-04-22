import React, { useEffect, useMemo, useState } from 'react';
import { Bluetooth, QrCode, KeyRound, Smartphone } from 'lucide-react';
import Modal from '../ui/Modal';
import Tabs from '../ui/Tabs';
import DeviceQRCode from '../ui/DeviceQRCode';
import { apiFetch } from '../lib/api';

/**
 * PairDeviceModal — four ways to pair a device:
 * 1) QR (phone / tablet scans to auth)
 * 2) BLE (browser Bluetooth API if available)
 * 3) HUP token (vendor-provided node id + shared secret)
 * 4) Share camera from phone (zero-install browser getUserMedia flow)
 */
export default function PairDeviceModal({ open, onClose, onPaired }) {
  const [tab, setTab] = useState('qr');
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
          { id: 'qr', label: 'QR' },
          { id: 'phone_camera', label: 'Share camera from phone' },
          { id: 'ble', label: 'Bluetooth' },
          { id: 'token', label: 'HUP token' },
        ]}
      />
      <div className="v2-pair-body">
        {tab === 'qr' && <QRTab />}
        {tab === 'phone_camera' && <PhoneCameraTab />}
        {tab === 'ble' && <BLETab onPaired={onPaired} />}
        {tab === 'token' && <TokenTab onPaired={onPaired} />}
      </div>
    </Modal>
  );
}

function PhoneCameraTab() {
  const [pairing, setPairing] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch('/api/devices/pair', {
        method: 'POST',
        body: JSON.stringify({ name: 'browser_camera_share' }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body?.error) {
        setError(body?.error || `${r.status}`);
        return;
      }
      setPairing(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { generate(); /* once on mount */ }, []);

  const shareUrl = useMemo(() => {
    if (!pairing?.token) return '';
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    return `${origin}/share/${pairing.token}`;
  }, [pairing]);

  return (
    <div className="v2-pair-phone-camera" data-testid="pair-phone-camera">
      <div className="v2-p v2-p--muted" style={{ marginBottom: 10 }}>
        <Smartphone size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
        Open this link on an iPhone / Android / any phone with a browser. They'll tap "Start sharing",
        grant camera + mic permission, and FERAL treats them as a HUP daemon named <code>browser_camera</code>.
        No app install.
      </div>
      {busy && <div className="v2-chip v2-chip--warn">Generating one-time link…</div>}
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
      {shareUrl && (
        <>
          <div className="v2-pair-qr" style={{ display: 'flex', justifyContent: 'center', marginBottom: 10 }}>
            <DeviceQRCode size={240} value={shareUrl} />
          </div>
          <div className="v2-p v2-p--tiny" style={{ wordBreak: 'break-all' }} data-testid="pair-phone-camera-url">
            {shareUrl}
          </div>
        </>
      )}
      <p className="v2-p v2-p--tiny v2-p--muted" style={{ marginTop: 8 }}>
        Privacy: the link works once. The Brain sees the camera as a disposable daemon and the phone's
        camera indicator is always visible to the user while they're sharing.
      </p>
    </div>
  );
}

function QRTab() {
  return (
    <div className="v2-pair-qr">
      <DeviceQRCode size={240} />
      <div className="v2-p v2-p--muted">
        <QrCode size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
        Scan from the FERAL iOS or Android app, or from a HUP-enabled device that supports QR handoff.
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
        Web Bluetooth isn't available in this browser. Use Chrome / Edge on a machine with a BLE radio, or use the desktop app for production BLE scanning.
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

function TokenTab({ onPaired }) {
  const [nodeId, setNodeId] = useState('');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await apiFetch('/api/devices/pair', {
        method: 'POST',
        body: JSON.stringify({ node_id: nodeId, secret, kind: 'hup' }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body?.error) {
        setError(body?.error || `${r.status}`);
      } else {
        setResult(body);
        if (onPaired) onPaired(body);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="v2-pair-token">
      <label className="v2-step-field">
        <span>Node ID</span>
        <input className="v2-input" value={nodeId} onChange={(e) => setNodeId(e.target.value)} placeholder="feral-w300-0001" required />
      </label>
      <label className="v2-step-field">
        <span>Shared secret</span>
        <input className="v2-input" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} required />
      </label>
      <div className="v2-p v2-p--muted">
        <KeyRound size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
        Vendors ship a token in their HUP daemon setup. Brain will accept the next WS connection from a matching node_id.
      </div>
      <button type="submit" className="v2-btn v2-btn--primary" disabled={busy}>
        {busy ? 'Pairing…' : 'Pair device'}
      </button>
      {result && <div className="v2-chip v2-chip--live">Paired — {result.node_id || nodeId}</div>}
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </form>
  );
}
