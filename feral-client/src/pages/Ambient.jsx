import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Heart, Wind, Calendar, Brain, Loader2,
} from 'lucide-react';
import TheOrb from '../components/TheOrb';
import { API_BASE } from '../config';
import { useToast } from '../components/Toast';

function formatClock(d) {
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true });
}

function formatDate(d) {
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
}

export default function Ambient() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [clock, setClock] = useState(new Date());
  const [dashboard, setDashboard] = useState(null);
  const [greeting, setGreeting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [orbMode, setOrbMode] = useState('idle');
  const refreshRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [dashRes, greetRes] = await Promise.all([
        fetch(`${API_BASE}/api/dashboard`).then(r => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/identity/greeting`).then(r => r.json()).catch(() => null),
      ]);
      if (dashRes) setDashboard(dashRes);
      if (greetRes && !greetRes.error) setGreeting(greetRes);
      setOrbMode(dashRes?.llm_available ? 'idle' : 'disconnected');
    } catch (e) {
      addToast(e.message || 'Failed to load ambient data');
      setOrbMode('disconnected');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    refreshRef.current = setInterval(refresh, 30_000);
    return () => clearInterval(refreshRef.current);
  }, [refresh]);

  useEffect(() => {
    const tick = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    const exit = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
      e.preventDefault();
      navigate(-1);
    };
    window.addEventListener('keydown', exit);
    return () => window.removeEventListener('keydown', exit);
  }, [navigate]);

  const health = dashboard?.health || {};
  const devices = dashboard?.devices || [];
  const memory = dashboard?.memory || {};
  const nextEvent = greeting?.next_event || greeting?.calendar_summary || null;
  const healthSummary = greeting?.health_summary || null;
  const lastMemory = greeting?.last_memory || null;

  if (loading) {
    return (
      <div className="fixed inset-0 bg-feral-bg flex items-center justify-center z-50" onClick={() => navigate(-1)}>
        <Loader2 size={32} className="animate-spin text-feral-accent" />
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 bg-feral-bg z-50 flex flex-col items-center justify-center select-none cursor-pointer overflow-hidden"
      onClick={() => navigate(-1)}
    >
      {/* Subtle grid overlay */}
      <div className="absolute inset-0 opacity-[0.02]" style={{
        backgroundImage: 'radial-gradient(circle, var(--color-feral-accent) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
      }} />

      {/* Top quadrants */}
      <div className="absolute top-0 left-0 right-0 flex justify-between px-8 pt-8 lg:px-16 lg:pt-12">
        {/* Top-left: Next event */}
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

        {/* Top-right: Health summary */}
        <div className="max-w-xs text-right">
          <div className="flex items-center gap-2 justify-end mb-2">
            <span className="text-[10px] text-feral-text-muted uppercase tracking-wider">Health</span>
            <Heart size={13} className="text-rose-400" />
          </div>
          {healthSummary ? (
            <p className="text-sm text-feral-text-secondary leading-relaxed">{healthSummary}</p>
          ) : (
            <p className="text-xs text-feral-text-muted">No health data</p>
          )}
        </div>
      </div>

      {/* Center: Orb + Clock */}
      <div className="flex flex-col items-center gap-6 z-10">
        <TheOrb size={80} mode={orbMode} connected={orbMode !== 'disconnected'} />
        <div className="text-center">
          <div className="text-5xl lg:text-6xl font-light text-feral-text tracking-tight tabular-nums">
            {formatClock(clock)}
          </div>
          <div className="text-sm text-feral-text-muted mt-2 tracking-wide">
            {formatDate(clock)}
          </div>
        </div>
      </div>

      {/* Bottom quadrants */}
      <div className="absolute bottom-0 left-0 right-0 flex justify-between px-8 pb-8 lg:px-16 lg:pb-12">
        {/* Bottom-left: HR + SpO2 */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Heart size={13} className="text-rose-400" />
            <span className="text-[10px] text-feral-text-muted uppercase tracking-wider">Vitals</span>
          </div>
          <div className="flex items-end gap-6">
            <div>
              <div className="text-3xl font-bold text-rose-400 tabular-nums leading-none">
                {health.heart_rate || '--'}
              </div>
              <div className="text-[10px] text-feral-text-muted mt-1">BPM</div>
            </div>
            <div>
              <div className="text-3xl font-bold text-feral-accent tabular-nums leading-none">
                {health.spo2 || '--'}
              </div>
              <div className="text-[10px] text-feral-text-muted mt-1">SpO2 %</div>
            </div>
          </div>
        </div>

        {/* Bottom-right: Last memory */}
        <div className="max-w-xs text-right">
          <div className="flex items-center gap-2 justify-end mb-2">
            <span className="text-[10px] text-feral-text-muted uppercase tracking-wider">Last Memory</span>
            <Brain size={13} className="text-feral-accent" />
          </div>
          {lastMemory ? (
            <p className="text-sm text-feral-text-secondary leading-relaxed italic">"{lastMemory}"</p>
          ) : (
            <p className="text-xs text-feral-text-muted">No recent memories</p>
          )}
        </div>
      </div>

      {/* Exit hint */}
      <div className="absolute bottom-3 left-1/2 -translate-x-1/2">
        <span className="text-[10px] text-feral-text-muted/40">press any key or tap to exit</span>
      </div>
    </div>
  );
}
