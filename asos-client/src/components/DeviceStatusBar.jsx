import React from 'react';
import { Monitor, Smartphone, Watch, Glasses, Home } from 'lucide-react';

const DEVICE_DEFS = [
  { key: 'desktop',    icon: Monitor,    label: 'Desktop' },
  { key: 'phone',      icon: Smartphone, label: 'Phone' },
  { key: 'wristband',  icon: Watch,      label: 'Wristband' },
  { key: 'glasses',    icon: Glasses,    label: 'Glasses' },
  { key: 'smart_home', icon: Home,       label: 'Smart Home' },
];

export default function DeviceStatusBar({ devices = [], hr }) {
  const connectedIds = new Set(devices.map(d => (d.type || d.node_id || '').toLowerCase()));
  const desktopAlways = true;

  return (
    <div className="flex items-center gap-1 overflow-x-auto px-4 py-2 bg-asos-surface/60 border-b border-asos-border backdrop-blur-md">
      {DEVICE_DEFS.map(({ key, icon: Icon, label }) => {
        const connected = key === 'desktop' ? desktopAlways : connectedIds.has(key);
        const metric = key === 'wristband' && hr ? `${hr} bpm` : null;

        return (
          <div
            key={key}
            className={`device-chip flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
              connected
                ? 'bg-asos-accent-dim text-asos-accent border border-asos-accent/20 device-chip-in'
                : 'bg-asos-card text-asos-text-muted border border-asos-border'
            }`}
          >
            <Icon size={13} className="flex-shrink-0" />
            <span className="hidden sm:inline">{label}</span>
            {connected && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_4px_#34d399] flex-shrink-0" />
            )}
            {metric && (
              <span className="text-[10px] font-mono text-rose-400 ml-0.5">{metric}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
