import React, { useCallback, useEffect, useState } from 'react';
import { Plus, RefreshCw, Zap, Radio, Wifi } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Modal from '../ui/Modal';
import StatusDot from '../ui/StatusDot';
import EmptyState from '../ui/EmptyState';
import PairDeviceModal from '../components/PairDeviceModal';
import { apiJson, apiFetch } from '../lib/api';

/**
 * Devices — paired list + HUP mesh. Click a device for detail + actuator
 * invoke. Uses Brain's real endpoints:
 *   GET /api/devices/paired, /api/hardware/mesh
 *   GET /api/hardware/device/{id}, /api/hardware/context
 *   POST /api/hardware/invoke (or /api/hardware/execute)
 *   DELETE /api/devices/{device_id}
 */
export default function Devices() {
  const [paired, setPaired] = useState([]);
  const [mesh, setMesh] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showPair, setShowPair] = useState(false);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [p, m] = await Promise.allSettled([
        apiJson('/api/devices/paired'),
        apiJson('/api/hardware/mesh'),
      ]);
      if (p.status === 'fulfilled') setPaired(p.value?.devices || []);
      if (m.status === 'fulfilled') setMesh(m.value?.nodes || []);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, [refresh]);

  const forget = async (id) => {
    if (!window.confirm(`Forget device ${id}? This removes the pairing.`)) return;
    await apiFetch(`/api/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
    refresh();
  };

  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="Devices"
        actions={(
          <>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh} aria-label="Refresh"><RefreshCw size={13} /></button>
            <button type="button" className="v2-btn v2-btn--primary" onClick={() => setShowPair(true)}>
              <Plus size={13} /> Pair new device
            </button>
          </>
        )}
      >
        {error && <div className="v2-chip v2-chip--error">{error}</div>}
        {loading && <EmptyState title="Scanning…" />}

        {!loading && paired.length === 0 && mesh.length === 0 && (
          <EmptyState
            title="No devices paired yet"
            hint="Pair an iPhone, wristband, smart glasses, or any HUP daemon. FERAL sees their sensors + fires their actuators."
            action={<button type="button" className="v2-btn v2-btn--primary" onClick={() => setShowPair(true)}>Pair your first device</button>}
          />
        )}
      </Pane>

      {paired.length > 0 && (
        <Pane title={`Paired (${paired.length})`}>
          <div className="v2-device-grid">
            {paired.map((d, i) => (
              <Glass key={d.device_id || d.id || i} level={0} radius="md" padding="md" className="v2-device-card" onClick={() => setSelected({ ...d, _source: 'paired' })} role="button" tabIndex={0}>
                <header className="v2-device-head">
                  <StatusDot tone={d.connected === false ? 'off' : 'live'} pulse={d.connected !== false} />
                  <h3 className="v2-device-name">{d.name || d.device_id || d.id || 'Device'}</h3>
                </header>
                <div className="v2-device-meta">{d.type || d.kind || 'generic'}</div>
                {d.capabilities && (
                  <div className="v2-device-caps">
                    {(Array.isArray(d.capabilities) ? d.capabilities : Object.keys(d.capabilities || {})).slice(0, 5).map((c, ci) => (
                      <span key={ci} className="v2-chip">{String(c)}</span>
                    ))}
                  </div>
                )}
              </Glass>
            ))}
          </div>
        </Pane>
      )}

      {mesh.length > 0 && (
        <Pane title={`HUP mesh (${mesh.length})`}>
          <div className="v2-device-grid">
            {mesh.map((n, i) => (
              <Glass key={n.node_id || i} level={0} radius="md" padding="md" className="v2-device-card" onClick={() => setSelected({ ...n, _source: 'mesh' })} role="button" tabIndex={0}>
                <header className="v2-device-head">
                  <StatusDot tone={n.online ? 'live' : 'off'} pulse={n.online} />
                  <h3 className="v2-device-name">{n.name || n.node_id}</h3>
                </header>
                <div className="v2-device-meta">
                  <Radio size={10} style={{ verticalAlign: 'text-bottom' }} /> HUP {n.hup_version || '1.x'}
                  {n.signal != null && <> · <Wifi size={10} style={{ verticalAlign: 'text-bottom' }} /> {Math.round(n.signal)}%</>}
                </div>
                {n.capabilities && (
                  <div className="v2-device-caps">
                    {(Array.isArray(n.capabilities) ? n.capabilities : Object.keys(n.capabilities || {})).slice(0, 5).map((c, ci) => (
                      <span key={ci} className="v2-chip">{String(c)}</span>
                    ))}
                  </div>
                )}
              </Glass>
            ))}
          </div>
        </Pane>
      )}

      <PairDeviceModal open={showPair} onClose={() => setShowPair(false)} onPaired={() => { setShowPair(false); refresh(); }} />
      {selected && <DeviceDetailModal device={selected} onClose={() => setSelected(null)} onForget={forget} />}
    </div>
  );
}

function DeviceDetailModal({ device, onClose, onForget }) {
  const [detail, setDetail] = useState(device);
  const [busy, setBusy] = useState(false);
  const [invoke, setInvoke] = useState({ method: '', args: '{}' });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const id = device.device_id || device.node_id || device.id;

  useEffect(() => {
    if (!id) return;
    apiJson(`/api/hardware/device/${encodeURIComponent(id)}`).then(setDetail).catch(() => {});
  }, [id]);

  const doInvoke = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      let args = {};
      try { args = JSON.parse(invoke.args); } catch { /* ignore */ }
      const r = await apiFetch('/api/hardware/invoke', {
        method: 'POST',
        body: JSON.stringify({ device_id: id, method: invoke.method, args }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body?.error) {
        setError(body?.error || `${r.status}`);
      } else {
        setResult(body);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const caps = detail.capabilities || device.capabilities;
  const capList = Array.isArray(caps) ? caps : Object.keys(caps || {});

  return (
    <Modal
      open
      onClose={onClose}
      title={device.name || id || 'Device'}
      size="lg"
      actions={(
        <>
          <button type="button" className="v2-btn" onClick={onClose}>Close</button>
          <button type="button" className="v2-btn" onClick={() => onForget(id)}>Forget device</button>
        </>
      )}
    >
      <div className="v2-setting-stack">
        <div className="v2-setting-row">
          <div className="v2-setting-label"><div>ID</div></div>
          <div className="v2-setting-control"><code className="v2-code-inline">{id}</code></div>
        </div>
        <div className="v2-setting-row">
          <div className="v2-setting-label"><div>Type</div></div>
          <div className="v2-setting-control">{detail.type || detail.kind || '—'}</div>
        </div>
        <div className="v2-setting-row">
          <div className="v2-setting-label"><div>Source</div></div>
          <div className="v2-setting-control">{device._source || 'unknown'}</div>
        </div>
        {capList.length > 0 && (
          <div className="v2-setting-row">
            <div className="v2-setting-label"><div>Capabilities</div></div>
            <div className="v2-setting-control v2-device-caps">
              {capList.map((c, i) => <span key={i} className="v2-chip">{String(c)}</span>)}
            </div>
          </div>
        )}
      </div>

      <div className="v2-p" style={{ marginTop: 16, fontWeight: 600 }}>
        <Zap size={14} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />
        Invoke actuator
      </div>
      <form onSubmit={doInvoke} className="v2-setting-stack">
        <label className="v2-setting-row">
          <div className="v2-setting-label"><div>Method</div></div>
          <div className="v2-setting-control">
            <input
              className="v2-input"
              value={invoke.method}
              onChange={(e) => setInvoke((s) => ({ ...s, method: e.target.value }))}
              placeholder="set_brightness, buzz, stream_start, …"
              required
            />
          </div>
        </label>
        <label className="v2-setting-row">
          <div className="v2-setting-label"><div>Args (JSON)</div></div>
          <div className="v2-setting-control" style={{ minWidth: 240, flex: 1 }}>
            <textarea className="v2-code-editor" rows={3} value={invoke.args} onChange={(e) => setInvoke((s) => ({ ...s, args: e.target.value }))} />
          </div>
        </label>
        <div className="v2-forge-actions">
          <button type="submit" className="v2-btn v2-btn--primary" disabled={busy || !invoke.method}>
            {busy ? 'Invoking…' : 'Invoke'}
          </button>
        </div>
      </form>
      {result && <pre className="v2-code">{JSON.stringify(result, null, 2)}</pre>}
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </Modal>
  );
}
