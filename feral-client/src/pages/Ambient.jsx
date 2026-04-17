import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Heart, Brain, Calendar, Thermometer, Battery, Activity,
} from 'lucide-react';
import TheOrb from '../components/TheOrb';
import SomaticWallpaper from '../components/SomaticWallpaper';
import { API_BASE, WS_BASE } from '../config';

function formatClock(d) {
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true });
}

function formatDate(d) {
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
}

const MODES = [
  { key: 'briefing', label: 'Briefing', shortcut: '1' },
  { key: 'desk', label: 'Desk', shortcut: '2' },
  { key: 'wind_down', label: 'Wind-Down', shortcut: '3' },
];

const IDLE_TIMEOUT_MS = 5 * 60 * 1000;

function somaticOrbMode(cognitiveLoad) {
  if (cognitiveLoad > 0.7) return 'alert';
  if (cognitiveLoad > 0.4) return 'thinking';
  return 'idle';
}

export default function Ambient() {
  const [mode, setMode] = useState('desk');
  const [time, setTime] = useState(new Date());
  const [dashboard, setDashboard] = useState(null);
  const [greeting, setGreeting] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [somatic, setSomatic] = useState({ cognitive_load: 0 });
  const [liveVitals, setLiveVitals] = useState({});
  const [toast, setToast] = useState(null);
  const [isDim, setIsDim] = useState(false);

  const wsRef = useRef(null);
  const idleTimerRef = useRef(null);
  const navigate = useNavigate();

  // ── Idle timer ────────────────────────────────────────────
  const resetIdle = useCallback(() => {
    setIsDim(false);
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    idleTimerRef.current = setTimeout(() => setIsDim(true), IDLE_TIMEOUT_MS);
  }, []);

  // ── REST initial load + 30s fallback poll ────────────────
  useEffect(() => {
    const load = async () => {
      const [d, g, s] = await Promise.all([
        fetch(`${API_BASE}/api/dashboard`).then(r => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/identity/greeting`).then(r => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/ambient/snapshot`).then(r => r.json()).catch(() => null),
      ]);
      if (d) setDashboard(d);
      if (g && !g.error) setGreeting(g);
      if (s) {
        setSnapshot(s);
        if (s.vitals) setLiveVitals(prev => ({ ...prev, ...s.vitals }));
        if (s.suggested_mode) setMode(s.suggested_mode);
      }
      if (d?.somatic) setSomatic(d.somatic);
    };
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, []);

  // ── WebSocket for live updates ───────────────────────────
  useEffect(() => {
    let ws;
    try {
      ws = new WebSocket(`${WS_BASE}/v1/session`);
      wsRef.current = ws;
    } catch {
      return;
    }

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        const p = msg.payload || msg.data || {};

        if (msg.type === 'device_telemetry' || p.heart_rate !== undefined) {
          const hr = p.heart_rate || p.wristband?.heart_rate;
          if (hr) setLiveVitals(v => ({ ...v, heart_rate: hr }));
          if (p.spo2 !== undefined) setLiveVitals(v => ({ ...v, spo2: p.spo2 }));
          if (p.skin_temperature_c !== undefined) setLiveVitals(v => ({ ...v, skin_temperature_c: p.skin_temperature_c }));
          if (p.battery_pct !== undefined) setLiveVitals(v => ({ ...v, battery_pct: p.battery_pct }));
        }

        if (msg.type === 'state_push' && msg.event === 'proactive_alert') {
          setToast(p);
          setTimeout(() => setToast(null), 5000);
        }

        if (msg.type === 'brain_event' && p.event === 'somatic_update') {
          setSomatic(p.data || {});
        }

        if (msg.type === 'state_push' && msg.event === 'dashboard_update') {
          if (p.somatic) setSomatic(p.somatic);
          setDashboard(p);
        }
      } catch (e) {
        console.warn('Ambient WS parse error:', e);
      }
    };

    return () => {
      try { ws.close(); } catch { /* noop */ }
    };
  }, []);

  // ── Clock tick ────────────────────────────────────────────
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // ── Idle detection ────────────────────────────────────────
  useEffect(() => {
    resetIdle();
    const onInput = () => resetIdle();
    window.addEventListener('keydown', onInput);
    window.addEventListener('mousemove', onInput);
    window.addEventListener('click', onInput);
    return () => {
      window.removeEventListener('keydown', onInput);
      window.removeEventListener('mousemove', onInput);
      window.removeEventListener('click', onInput);
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    };
  }, [resetIdle]);

  // ── Keyboard shortcuts ────────────────────────────────────
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === '1') setMode('briefing');
      else if (e.key === '2') setMode('desk');
      else if (e.key === '3') setMode('wind_down');
      else if (e.key === 'Escape') navigate(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate]);

  // ── Derived state ─────────────────────────────────────────
  const cognitiveLoad = somatic.cognitive_load || 0;
  const hr = liveVitals.heart_rate || dashboard?.health?.heart_rate || 0;
  const spo2 = liveVitals.spo2 || dashboard?.health?.spo2 || 0;
  const skinTemp = liveVitals.skin_temperature_c || 0;
  const battery = liveVitals.battery_pct ?? 100;
  const nextEvent = greeting?.next_event || greeting?.calendar_summary || null;
  const lastMemory = greeting?.last_memory || null;
  const orbMode = somaticOrbMode(cognitiveLoad);

  return (
    <div
      className="fixed inset-0 bg-feral-bg z-50 flex flex-col items-center justify-center select-none overflow-hidden"
      style={{
        transition: 'opacity 1.5s ease',
        opacity: isDim ? 0.4 : 1,
      }}
    >
      <SomaticWallpaper cognitiveLoad={cognitiveLoad} heartRate={hr} />

      {/* Subtle grid overlay */}
      <div className="absolute inset-0 opacity-[0.02] z-[1]" style={{
        backgroundImage: 'radial-gradient(circle, var(--color-feral-accent) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
      }} />

      {/* ─── Top quadrants ─── */}
      <div className="absolute top-0 left-0 right-0 flex justify-between px-8 pt-8 lg:px-16 lg:pt-12 z-10">
        {/* Next event */}
        <div className="max-w-xs">
          <div className="flex items-center gap-2 mb-2">
            <Calendar size={13} className="text-emerald-400" />
            <span className="text-[10px] text-feral-text-muted uppercase tracking-wider">Next Up</span>
          </div>
          {nextEvent ? (
            <p className="text-sm text-feral-text-secondary leading-relaxed">{nextEvent}</p>
          ) : (
            <p className="text-xs text-feral-text-muted">Nothing scheduled</p>
          )}
        </div>

        {/* Vitals chips */}
        <div className="flex items-start gap-4">
          <VitalChip icon={Heart} label="BPM" value={hr || '--'} color="text-rose-400" />
          <VitalChip icon={Activity} label="SpO2" value={spo2 ? `${spo2}%` : '--'} color="text-cyan-400" />
          {skinTemp > 0 && (
            <VitalChip icon={Thermometer} label="Temp" value={`${skinTemp.toFixed(1)}°`} color="text-amber-400" />
          )}
          {battery < 100 && (
            <VitalChip icon={Battery} label="Band" value={`${battery}%`} color="text-emerald-400" />
          )}
        </div>
      </div>

      {/* ─── Center: Orb + Clock ─── */}
      <div className="flex flex-col items-center gap-6 z-10">
        <TheOrb size={80} mode={orbMode} connected={orbMode !== 'disconnected'} />
        <div className="text-center">
          <div className="text-5xl lg:text-6xl font-light text-feral-text tracking-tight tabular-nums">
            {formatClock(time)}
          </div>
          <div className="text-sm text-feral-text-muted mt-2 tracking-wide">
            {formatDate(time)}
          </div>
        </div>
      </div>

      {/* ─── Mode-specific content ─── */}
      <div className="z-10 mt-8 text-center min-h-[60px]">
        {mode === 'desk' && (
          <DeskContent lastMemory={lastMemory} snapshot={snapshot} />
        )}
        {mode === 'briefing' && (
          <div className="text-feral-text-muted text-sm px-6 py-3 rounded-xl bg-white/5 border border-white/5">
            Briefing mode — coming in Sprint 3
          </div>
        )}
        {mode === 'wind_down' && (
          <div className="text-feral-text-muted text-sm px-6 py-3 rounded-xl bg-white/5 border border-white/5">
            Wind-Down mode — coming in Sprint 3
          </div>
        )}
      </div>

      {/* ─── Proactive toast ─── */}
      {toast && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 animate-in fade-in slide-in-from-bottom-4 duration-300">
          <div className="bg-feral-surface border border-feral-border rounded-xl px-5 py-3 shadow-xl max-w-md text-center">
            {toast.title && <div className="text-sm font-medium text-feral-text mb-1">{toast.title}</div>}
            <div className="text-xs text-feral-text-secondary">{toast.body || JSON.stringify(toast)}</div>
          </div>
        </div>
      )}

      {/* ─── Mode selector ─── */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1 bg-white/5 rounded-full p-1 border border-white/5">
        {MODES.map(m => (
          <button
            key={m.key}
            onClick={(e) => { e.stopPropagation(); setMode(m.key); }}
            className={`px-4 py-1.5 rounded-full text-xs font-medium transition-all ${
              mode === m.key
                ? 'bg-feral-accent/20 text-feral-accent'
                : 'text-feral-text-muted hover:text-feral-text-secondary'
            }`}
          >
            {m.label}
            <span className="ml-1.5 text-[9px] opacity-50">{m.shortcut}</span>
          </button>
        ))}
      </div>

      {/* Exit hint */}
      <div className="absolute bottom-2 left-1/2 -translate-x-1/2 z-10">
        <span className="text-[10px] text-feral-text-muted/30">Esc to exit</span>
      </div>
    </div>
  );
}


function VitalChip({ icon: Icon, label, value, color }) {
  return (
    <div className="text-right">
      <div className="flex items-center gap-1 justify-end mb-1">
        <span className="text-[9px] text-feral-text-muted uppercase tracking-wider">{label}</span>
        <Icon size={11} className={color} />
      </div>
      <div className={`text-lg font-semibold tabular-nums leading-none ${color}`}>{value}</div>
    </div>
  );
}


function DeskContent({ lastMemory, snapshot }) {
  return (
    <div className="flex flex-col items-center gap-3">
      {lastMemory && (
        <div className="max-w-sm text-center">
          <div className="flex items-center gap-2 justify-center mb-1">
            <Brain size={12} className="text-feral-accent" />
            <span className="text-[9px] text-feral-text-muted uppercase tracking-wider">Last Memory</span>
          </div>
          <p className="text-sm text-feral-text-secondary leading-relaxed italic">"{lastMemory}"</p>
        </div>
      )}
    </div>
  );
}
