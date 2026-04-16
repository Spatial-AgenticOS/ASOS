import React from 'react';
import { Monitor, Smartphone, Watch, Glasses, Home } from 'lucide-react';

const DEVICE_DEFS = [
  { key: 'desktop', icon: Monitor, label: 'Desktop' },
  { key: 'phone', icon: Smartphone, label: 'Phone' },
  { key: 'wristband', icon: Watch, label: 'Wristband' },
  { key: 'glasses', icon: Glasses, label: 'Glasses' },
  { key: 'smart_home', icon: Home, label: 'Smart Home' },
];

export default function DeviceStatusBar({ devices = [], hr, demo = false }) {
  if (devices.length === 0 && !demo) return null;

  const connectedTypes = new Set(
    devices.map(d => (d.type || d.device_type || '').toLowerCase()).filter(Boolean)
  );

  const visibleDefs = demo ? DEVICE_DEFS : DEVICE_DEFS.filter(d => connectedTypes.has(d.key));

  if (visibleDefs.length === 0) return null;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
      {demo && (
        <span style={{
          background: '#78350f',
          color: '#fbbf24',
          fontSize: 9,
          padding: '2px 8px',
          borderRadius: 4,
          fontWeight: 600,
        }}>
          DEMO
        </span>
      )}
      {visibleDefs.map(def => {
        const Icon = def.icon;
        const isConnected = demo ? false : connectedTypes.has(def.key);
        return (
          <div key={def.key} style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '4px 10px',
            background: isConnected ? 'rgba(16,185,129,0.1)' : demo ? 'rgba(251,191,36,0.1)' : 'rgba(39,39,42,0.5)',
            border: `1px solid ${isConnected ? '#10b981' : demo ? '#78350f' : '#3f3f46'}`,
            borderRadius: 6,
            fontSize: 11,
            color: isConnected ? '#10b981' : demo ? '#fbbf24' : '#71717a',
          }}>
            <Icon size={12} />
            <span>{def.label}</span>
            {isConnected && <span style={{ fontSize: 8 }}>●</span>}
          </div>
        );
      })}
      {hr > 0 && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '4px 10px',
          background: 'rgba(239,68,68,0.1)',
          border: '1px solid #ef4444',
          borderRadius: 6,
          fontSize: 11,
          color: '#ef4444',
        }}>
          <span>♥</span>
          <span>{hr} bpm</span>
        </div>
      )}
    </div>
  );
}
