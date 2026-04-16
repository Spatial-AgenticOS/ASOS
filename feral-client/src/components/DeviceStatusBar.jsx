import React from 'react';
import { Monitor, Smartphone, Watch, Glasses, Home } from 'lucide-react';

const DEVICE_DEFS = [
  { key: 'desktop', icon: Monitor, label: 'Desktop' },
  { key: 'phone', icon: Smartphone, label: 'Phone' },
  { key: 'wristband', icon: Watch, label: 'Wristband' },
  { key: 'glasses', icon: Glasses, label: 'Glasses' },
  { key: 'smart_home', icon: Home, label: 'Smart Home' },
];

export default function DeviceStatusBar({ devices = [], hr }) {
  if (devices.length === 0) return null;

  const connectedTypes = new Set(
    devices.map(d => (d.type || d.device_type || '').toLowerCase()).filter(Boolean)
  );

  const visibleDefs = DEVICE_DEFS.filter(d => connectedTypes.has(d.key));

  if (visibleDefs.length === 0) return null;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
      {visibleDefs.map(def => {
        const Icon = def.icon;
        return (
          <div key={def.key} style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '4px 10px',
            background: 'rgba(16,185,129,0.1)',
            border: '1px solid #10b981',
            borderRadius: 6,
            fontSize: 11,
            color: '#10b981',
          }}>
            <Icon size={12} />
            <span>{def.label}</span>
            <span style={{ fontSize: 8 }}>●</span>
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
