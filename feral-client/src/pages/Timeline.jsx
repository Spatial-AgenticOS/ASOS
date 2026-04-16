import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain, Heart, Calendar, ArrowLeft,
  Loader2, WifiOff,
} from 'lucide-react';
import { API_BASE } from '../config';
import { useToast } from '../components/Toast';

const FILTERS = [
  { key: 'all',       label: 'All' },
  { key: 'memories',  label: 'Memories' },
  { key: 'health',    label: 'Health' },
  { key: 'event',     label: 'Events' },
];

const TYPE_META = {
  memories: { icon: Brain,    color: 'text-feral-accent',  bg: 'bg-feral-accent-dim' },
  memory:   { icon: Brain,    color: 'text-feral-accent',  bg: 'bg-feral-accent-dim' },
  health:   { icon: Heart,    color: 'text-rose-400',      bg: 'bg-rose-400/10' },
  event:    { icon: Calendar, color: 'text-emerald-400',   bg: 'bg-emerald-400/10' },
};

function dateLabel(ts) {
  const d = new Date(ts);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const entry = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = (today - entry) / 86_400_000;
  if (diff < 1) return 'Today';
  if (diff < 2) return 'Yesterday';
  return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
}

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

export default function Timeline() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [entries, setEntries] = useState([]);
  const [activeFilter, setActiveFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const bottomRef = useRef(null);

  const fetchTimeline = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await fetch(`${API_BASE}/api/timeline?days=7&type=${activeFilter}`);
      const data = await res.json();
      setEntries(data.entries || data.items || data || []);
    } catch (e) {
      addToast(e.message || 'Failed to load timeline');
      setError(true);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [activeFilter]);

  useEffect(() => { fetchTimeline(); }, [fetchTimeline]);

  useEffect(() => {
    if (!loading && entries.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [loading, entries.length]);

  const grouped = entries.reduce((acc, entry) => {
    const ts = entry.timestamp ? (entry.timestamp > 1e12 ? entry.timestamp : entry.timestamp * 1000) : Date.now();
    const label = dateLabel(ts);
    if (!acc[label]) acc[label] = [];
    acc[label].push({ ...entry, _ts: ts });
    return acc;
  }, {});

  return (
    <div className="h-full flex flex-col bg-feral-bg">
      {/* Header */}
      <div className="flex-shrink-0 bg-feral-surface/80 backdrop-blur-xl border-b border-feral-border px-4 py-3">
        <div className="flex items-center gap-3 mb-3">
          <button onClick={() => navigate(-1)} className="p-1.5 rounded-lg hover:bg-feral-card transition">
            <ArrowLeft size={16} className="text-feral-text-secondary" />
          </button>
          <h1 className="text-lg font-bold tracking-tight">Timeline</h1>
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
          {FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => setActiveFilter(f.key)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition ${
                activeFilter === f.key
                  ? 'bg-feral-accent text-white'
                  : 'bg-feral-card border border-feral-border text-feral-text-secondary hover:text-feral-text hover:border-feral-border-bright'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {loading && (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={24} className="animate-spin text-feral-accent" />
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <WifiOff size={32} className="opacity-30" />
            <p className="text-sm text-feral-text-muted">Failed to load timeline</p>
            <button onClick={fetchTimeline} className="px-4 py-2 bg-feral-card border border-feral-border rounded-lg text-sm hover:bg-feral-card-hover transition">
              Retry
            </button>
          </div>
        )}

        {!loading && !error && entries.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <Calendar size={32} className="opacity-20" />
            <p className="text-sm text-feral-text-muted">No timeline entries yet</p>
            <p className="text-xs text-feral-text-muted">Memories, health data, and events will appear here</p>
          </div>
        )}

        {!loading && !error && entries.length > 0 && (
          <div className="relative pl-8">
            {/* Vertical cyan line */}
            <div className="absolute left-3 top-0 bottom-0 w-px bg-feral-accent/30" />

            {Object.entries(grouped).map(([label, items]) => (
              <div key={label} className="mb-6">
                {/* Date header */}
                <div className="relative flex items-center mb-4 -ml-8">
                  <div className="absolute left-3 w-2 h-2 rounded-full bg-feral-accent shadow-[0_0_6px_var(--color-feral-accent-glow)]" />
                  <span className="ml-8 text-xs font-semibold text-feral-text-secondary uppercase tracking-wider">
                    {label}
                  </span>
                </div>

                {/* Entries */}
                <div className="space-y-3">
                  {items
                    .sort((a, b) => a._ts - b._ts)
                    .map((entry, i) => {
                      const type = entry.type || 'memory';
                      const meta = TYPE_META[type] || TYPE_META.memory;
                      const Icon = meta.icon;

                      return (
                        <div key={entry.id || `${label}-${i}`} className="relative">
                          {/* Dot on the line */}
                          <div className={`absolute -left-8 top-4 w-2.5 h-2.5 rounded-full border-2 border-feral-bg ${meta.bg}`}>
                            <div className={`w-full h-full rounded-full ${meta.bg}`} />
                          </div>

                          {/* Card */}
                          <div className="bg-feral-card border border-feral-border rounded-xl p-4 hover:border-feral-border-bright transition">
                            <div className="flex items-start gap-3">
                              <div className={`p-2 rounded-lg ${meta.bg} flex-shrink-0`}>
                                <Icon size={14} className={meta.color} />
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between gap-2 mb-1">
                                  <span className="text-xs font-mono text-feral-text-muted">
                                    {formatTime(entry._ts)}
                                  </span>
                                  {entry.heart_rate && (
                                    <span className="flex items-center gap-1 text-[10px] text-rose-400 bg-rose-400/10 px-2 py-0.5 rounded-full">
                                      <Heart size={9} />
                                      {entry.heart_rate} bpm
                                    </span>
                                  )}
                                </div>
                                <p className="text-sm text-feral-text leading-relaxed">
                                  {entry.content || entry.summary || entry.text || entry.description || 'No content'}
                                </p>
                                {entry.tags && entry.tags.length > 0 && (
                                  <div className="flex flex-wrap gap-1 mt-2">
                                    {entry.tags.map(tag => (
                                      <span key={tag} className="text-[10px] text-feral-text-muted bg-feral-bg/30 px-1.5 py-0.5 rounded">
                                        {tag}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
