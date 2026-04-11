import React, { useState, useEffect } from 'react';
import { Monitor, Heart, Clock, Calendar } from 'lucide-react';

/**
 * Ambient Context Strip -- thin bar showing what FERAL currently knows.
 * Displays screen context, health, session timer, and next event.
 */
export default function AmbientStrip({ screenContext, hr, sessionStartTime, nextEvent }) {
  const [elapsed, setElapsed] = useState('');

  useEffect(() => {
    if (!sessionStartTime) return;
    const tick = () => {
      const mins = Math.floor((Date.now() - sessionStartTime) / 60000);
      if (mins < 1) setElapsed('just started');
      else if (mins < 60) setElapsed(`${mins}m`);
      else setElapsed(`${Math.floor(mins / 60)}h ${mins % 60}m`);
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => clearInterval(id);
  }, [sessionStartTime]);

  const hrColor = !hr ? '' : hr < 80 ? 'text-emerald-400' : hr < 100 ? 'text-amber-400' : 'text-rose-400';

  const items = [];

  if (screenContext) {
    items.push(
      <div key="screen" className="ambient-item-enter flex items-center gap-1.5 text-feral-text-secondary">
        <Monitor size={11} className="text-feral-text-muted flex-shrink-0" />
        <span className="truncate max-w-[180px]">{screenContext}</span>
      </div>
    );
  }

  if (hr) {
    items.push(
      <div key="hr" className="ambient-item-enter flex items-center gap-1.5">
        <Heart size={11} className={`${hrColor} flex-shrink-0`} />
        <span className={`font-mono ${hrColor}`}>{hr}</span>
        <span className="text-feral-text-muted">bpm</span>
      </div>
    );
  }

  if (elapsed) {
    items.push(
      <div key="timer" className="ambient-item-enter flex items-center gap-1.5 text-feral-text-secondary">
        <Clock size={11} className="text-feral-text-muted flex-shrink-0" />
        <span>{elapsed}</span>
      </div>
    );
  }

  if (nextEvent) {
    items.push(
      <div key="event" className="ambient-item-enter flex items-center gap-1.5 text-feral-text-secondary">
        <Calendar size={11} className="text-feral-text-muted flex-shrink-0" />
        <span className="truncate max-w-[160px]">{nextEvent}</span>
      </div>
    );
  }

  if (items.length === 0) return null;

  return (
    <div className="flex-shrink-0 flex items-center gap-3 px-4 py-1.5 bg-feral-surface/40 backdrop-blur-sm border-b border-feral-border text-[11px] overflow-x-auto">
      {items.map((item, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="text-feral-border-bright select-none">|</span>}
          {item}
        </React.Fragment>
      ))}
    </div>
  );
}
