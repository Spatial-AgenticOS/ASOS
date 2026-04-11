import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain, Cpu, Activity, Database, MessageSquare, Puzzle,
  Wifi, WifiOff, Zap, Eye, Shield, BookOpen, Clock, TrendingUp,
  Sparkles, Lock, CheckCircle, XCircle, AlertTriangle,
  Heart, Thermometer, Wind, Sun, CloudRain, RefreshCw,
  Search, Music, Home, Bluetooth, Radio, Globe,
  ArrowRight, ChevronRight, Loader2,
} from 'lucide-react';

import { API_BASE as API, WS_URL } from '../config';
import DeviceStatusBar from '../components/DeviceStatusBar';

export default function Dashboard() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState(null);
  const [info, setInfo] = useState(null);
  const [activity, setActivity] = useState([]);
  const [llmStatus, setLlmStatus] = useState(null);
  const [llmPresets, setLlmPresets] = useState([]);
  const [channelStats, setChannelStats] = useState({ active_channels: [], details: {}, channel_count: 0 });
  const [genuiProviders, setGenuiProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [quickActionLoading, setQuickActionLoading] = useState(null);

  const refresh = useCallback(() => {
    Promise.all([
      fetch(`${API}/api/dashboard`).then(r => r.json()).catch(() => null),
      fetch(`${API}/api/system/info`).then(r => r.json()).catch(() => null),
      fetch(`${API}/api/activity`).then(r => r.json()).catch(() => null),
      fetch(`${API}/api/llm/status`).then(r => r.json()).catch(() => null),
      fetch(`${API}/api/llm/presets`).then(r => r.json()).catch(() => null),
      fetch(`${API}/api/channels`).then(r => r.json()).catch(() => null),
      fetch(`${API}/api/genui/providers`).then(r => r.json()).catch(() => null),
    ]).then(([dash, sys, act, llm, presets, channels, genui]) => {
      if (dash) setDashboard(dash);
      if (sys) setInfo(sys);
      if (act) setActivity(act.entries || []);
      if (llm && !llm.error) setLlmStatus(llm);
      if (presets && !presets.error) setLlmPresets(presets.presets || []);
      if (channels && !channels.error) setChannelStats(channels);
      if (genui && !genui.error) setGenuiProviders(genui.providers || []);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    refresh();
    let ws;
    try {
      ws = new WebSocket(WS_URL);
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'state_push' && msg.event === 'dashboard_update' && msg.data) {
            setDashboard(msg.data);
          }
        } catch {}
      };
    } catch {}
    return () => { if (ws) ws.close(); };
  }, [refresh]);

  const executeQuickAction = async (action) => {
    setQuickActionLoading(action);
    try {
      const ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        ws.send(JSON.stringify({
          type: 'text_command',
          payload: { text: action },
        }));
        setTimeout(() => ws.close(), 5000);
      };
    } catch { /* ignore */ }
    setTimeout(() => setQuickActionLoading(null), 3000);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 border-2 border-asos-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!dashboard && !info) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <WifiOff size={40} className="opacity-30" />
        <p className="text-sm opacity-50">Cannot connect to THEORA Brain</p>
        <button onClick={refresh} className="px-4 py-2 bg-asos-card border border-asos-border rounded-lg text-sm hover:bg-asos-card-hover">
          Retry
        </button>
      </div>
    );
  }

  const d = dashboard || {};
  const mem = d.memory || info?.memory || {};
  const health = d.health || {};
  const devices = d.devices || [];
  const deviceCount = d.device_count || 0;
  const sessionCount = d.session_count || 0;
  const skillsCount = d.skills_count || info?.skills?.length || 0;

  return (
    <div className="h-full overflow-y-auto">
      <DeviceStatusBar devices={devices} hr={health.heart_rate} />
      <div className="max-w-6xl mx-auto p-4 lg:p-8 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Control Center</h1>
            <p className="text-xs text-asos-text-muted mt-0.5">
              THEORA Brain v{info?.version || '1.0.0'}
              {d.llm_available && <span className="ml-2 text-green-400">LLM ready</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={refresh} className="p-2 rounded-lg hover:bg-asos-card transition">
              <RefreshCw size={16} className="text-asos-text-secondary" />
            </button>
            <button
              onClick={() => navigate('/chat')}
              className="flex items-center gap-2 px-4 py-2 bg-asos-accent text-white rounded-lg text-sm font-medium hover:bg-asos-accent/90 transition active:scale-95"
            >
              <MessageSquare size={14} /> Chat
            </button>
          </div>
        </div>

        {/* Top Status Row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatusCard icon={Wifi} label="Sessions" value={sessionCount} color="#34d399" />
          <StatusCard icon={Cpu} label="Devices" value={deviceCount} color="#06b6d4"
            subtitle={deviceCount > 0 ? `${deviceCount} connected` : 'none connected'} />
          <StatusCard icon={Puzzle} label="Skills" value={skillsCount} color="#fbbf24" />
          <StatusCard icon={Activity} label="Audio"
            value={d.audio_available ? 'Ready' : 'Off'}
            color={d.audio_available ? '#34d399' : '#71717a'} />
        </div>

        {/* Main Grid: Devices + Health */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Devices Panel */}
          <div className="bg-asos-card border border-asos-border rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Bluetooth size={16} className="text-asos-accent" />
                <h2 className="font-semibold text-sm">Connected Devices</h2>
              </div>
              <button onClick={() => navigate('/settings')}
                className="text-xs text-asos-accent hover:underline flex items-center gap-1">
                Manage <ChevronRight size={12} />
              </button>
            </div>
            {devices.length > 0 ? (
              <div className="space-y-2">
                {devices.map(dev => (
                  <div key={dev.node_id} className="flex items-center gap-3 bg-asos-bg/30 rounded-lg px-4 py-3">
                    <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_6px_#22c55e]" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-mono truncate">{dev.node_id}</div>
                      <div className="text-xs text-asos-text-muted capitalize">{dev.type}</div>
                    </div>
                    <Radio size={14} className="text-green-400" />
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <Bluetooth size={28} className="mx-auto opacity-20 mb-3" />
                <p className="text-sm text-asos-text-muted">No devices connected</p>
                <p className="text-xs text-asos-text-muted mt-1">
                  Use the hardware daemon or phone bridge to connect
                </p>
                <button onClick={() => navigate('/settings')}
                  className="mt-3 text-xs text-asos-accent hover:underline">
                  Connect a device
                </button>
              </div>
            )}
          </div>

          {/* Health Metrics */}
          <div className="bg-asos-card border border-asos-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Heart size={16} className="text-red-400" />
              <h2 className="font-semibold text-sm">Live Health</h2>
            </div>
            {Object.keys(health).length > 0 ? (
              <div className="grid grid-cols-3 gap-4">
                {health.heart_rate && (
                  <HealthMetric icon={Heart} label="Heart Rate" value={`${health.heart_rate}`} unit="bpm" color="#f87171" />
                )}
                {health.spo2 && (
                  <HealthMetric icon={Wind} label="SpO2" value={`${health.spo2}`} unit="%" color="#22d3ee" />
                )}
                {health.temperature && (
                  <HealthMetric icon={Thermometer} label="Temp" value={`${health.temperature}`} unit="°C" color="#fbbf24" />
                )}
              </div>
            ) : (
              <div className="text-center py-8">
                <Heart size={28} className="mx-auto opacity-20 mb-3" />
                <p className="text-sm text-asos-text-muted">No health data</p>
                <p className="text-xs text-asos-text-muted mt-1">
                  Connect a wristband or phone to stream biometrics
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Provider / Channel Plane */}
        <div className="bg-asos-card border border-asos-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Sparkles size={16} className="text-asos-accent" />
            <h2 className="font-semibold text-sm">Provider and Channel Plane</h2>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="bg-asos-bg/30 border border-asos-border rounded-lg p-3">
              <div className="text-xs text-asos-text-secondary uppercase tracking-wider mb-2">LLM Provider</div>
              <div className="text-sm font-semibold capitalize">
                {llmStatus?.provider || info?.config?.llm?.provider || 'unknown'}
              </div>
              <div className="text-xs text-asos-text-muted font-mono mt-1">
                {llmStatus?.model || info?.config?.llm?.model || 'n/a'}
              </div>
              <div className={`text-[11px] mt-2 ${llmStatus?.available ? 'text-green-400' : 'text-yellow-400'}`}>
                {llmStatus?.available ? 'Connected' : 'Fallback / unavailable'}
              </div>
              <div className="text-[11px] text-asos-text-muted mt-1">
                Presets: {llmPresets.length}
              </div>
            </div>

            <div className="bg-asos-bg/30 border border-asos-border rounded-lg p-3">
              <div className="text-xs text-asos-text-secondary uppercase tracking-wider mb-2">Channels</div>
              <div className="text-sm font-semibold">{channelStats.channel_count || 0} active</div>
              {(channelStats.active_channels || []).length > 0 ? (
                <div className="mt-2 space-y-1">
                  {(channelStats.active_channels || []).map((ch) => (
                    <div key={ch} className="text-[11px] text-asos-text-secondary flex items-center justify-between">
                      <span className="capitalize">{ch}</span>
                      <span className="text-asos-text-muted">
                        {channelStats.details?.[ch]?.known_chats || 0} chats
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[11px] text-asos-text-muted mt-2">No active channels</div>
              )}
            </div>

            <div className="bg-asos-bg/30 border border-asos-border rounded-lg p-3">
              <div className="text-xs text-asos-text-secondary uppercase tracking-wider mb-2">Providers + Devices</div>
              <div className="text-[11px] text-asos-text-secondary">GenUI Providers: {genuiProviders.length}</div>
              <div className="text-[11px] text-asos-text-secondary mt-1">Connected Devices: {devices.length}</div>
              {genuiProviders.length > 0 && (
                <div className="mt-2 space-y-1">
                  {genuiProviders.slice(0, 3).map((p) => (
                    <div key={p.provider_id} className="text-[11px] text-asos-text-secondary truncate">
                      {p.name || p.provider_id} · {p.components?.length || 0} comps · {p.surface_ids?.length || 0} surfaces · {p.cache_policy?.mode || 'static'} cache
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="bg-asos-card border border-asos-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Zap size={16} className="text-yellow-400" />
            <h2 className="font-semibold text-sm">Quick Actions</h2>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <QuickAction icon={Search} label="Search the Web"
              onClick={() => executeQuickAction("What's the latest tech news?")}
              loading={quickActionLoading === "What's the latest tech news?"} />
            <QuickAction icon={Sun} label="Get Weather"
              onClick={() => executeQuickAction("What's the weather like right now?")}
              loading={quickActionLoading === "What's the weather like right now?"} />
            <QuickAction icon={Brain} label="Memory Status"
              onClick={() => executeQuickAction("Show me my memory stats")}
              loading={quickActionLoading === "Show me my memory stats"} />
            <QuickAction icon={Globe} label="System Check"
              onClick={() => executeQuickAction("Run a system health check")}
              loading={quickActionLoading === "Run a system health check"} />
          </div>
        </div>

        {/* Memory + System Status */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Memory */}
          <div className="bg-asos-card border border-asos-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Database size={16} className="text-asos-accent" />
              <h2 className="font-semibold text-sm">Memory</h2>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <MemoryMetric label="Notes" value={mem.notes || 0} icon={BookOpen} />
              <MemoryMetric label="Episodes" value={mem.episodes || 0} icon={Clock} />
              <MemoryMetric label="Knowledge" value={mem.knowledge_triples || 0} icon={Brain} />
              <MemoryMetric label="Sessions" value={mem.active_working_sessions || 0} icon={Zap} />
            </div>
          </div>

          {/* System Features */}
          <div className="bg-asos-card border border-asos-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Shield size={16} className="text-asos-accent" />
              <h2 className="font-semibold text-sm">System Status</h2>
            </div>
            <div className="space-y-2">
              <FeatureRow label="WASM Sandbox" active={d.wasm_available} />
              <FeatureRow label="Wake Word" active={d.wake_word_enabled} />
              <FeatureRow label="Federated Sync" active={d.sync?.running} />
              <FeatureRow label="Audio Pipeline" active={d.audio_available} />
              <FeatureRow label="LLM Connected" active={d.llm_available} />
              <FeatureRow label="Sync Peers" active={(d.sync?.peer_count || 0) > 0}
                detail={`${d.sync?.peer_count || 0} peers`} />
            </div>
          </div>
        </div>

        {/* Activity Feed */}
        <div className="bg-asos-card border border-asos-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Activity size={16} className="text-green-400" />
            <h2 className="font-semibold text-sm">Activity Feed</h2>
          </div>
          {activity.length > 0 ? (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {activity.slice().reverse().map((entry, i) => (
                <div key={i} className="flex items-center gap-3 text-xs bg-asos-bg/20 rounded-lg px-3 py-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" />
                  <span className="text-asos-text-secondary font-mono flex-shrink-0">
                    {new Date(entry.timestamp * 1000).toLocaleTimeString()}
                  </span>
                  <span className="text-asos-text-secondary capitalize font-medium">{entry.action}</span>
                  <span className="text-asos-text-muted truncate">{entry.detail}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-asos-text-muted text-center py-4">
              No activity yet — start chatting or connect a device
            </p>
          )}
        </div>

        {/* Skills (compact) */}
        {info?.skills && info.skills.length > 0 && (
          <div className="bg-asos-card border border-asos-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Puzzle size={16} className="text-asos-accent" />
              <h2 className="font-semibold text-sm">Skills ({info.skills.length})</h2>
            </div>
            <div className="flex flex-wrap gap-2">
              {info.skills.map(s => (
                <span key={s.skill_id}
                  className="text-xs bg-asos-bg/30 text-asos-text-secondary px-3 py-1.5 rounded-full">
                  {s.name}
                  <span className="text-asos-text-muted ml-1">·{s.endpoints}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatusCard({ icon: Icon, label, value, subtitle, color }) {
  return (
    <div className="bg-asos-card border border-asos-border rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={14} style={{ color }} />
        <span className="text-[10px] text-asos-text-secondary uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-2xl font-bold" style={{ color }}>{value}</div>
      {subtitle && <div className="text-[10px] text-asos-text-muted mt-0.5 truncate">{subtitle}</div>}
    </div>
  );
}

function MemoryMetric({ label, value, icon: Icon }) {
  return (
    <div className="flex items-center gap-3 bg-asos-bg/20 rounded-lg px-3 py-2.5">
      <Icon size={14} className="opacity-40 flex-shrink-0" />
      <div>
        <div className="text-lg font-bold leading-none">{value}</div>
        <div className="text-[10px] text-asos-text-secondary mt-0.5">{label}</div>
      </div>
    </div>
  );
}

function HealthMetric({ icon: Icon, label, value, unit, color }) {
  return (
    <div className="text-center">
      <Icon size={18} className="mx-auto mb-2" style={{ color }} />
      <div className="text-2xl font-bold" style={{ color }}>{value}</div>
      <div className="text-[10px] text-asos-text-secondary">{unit}</div>
      <div className="text-[10px] text-asos-text-muted mt-0.5">{label}</div>
    </div>
  );
}

function FeatureRow({ label, active, detail }) {
  return (
    <div className="flex items-center justify-between bg-asos-bg/20 rounded-lg px-3 py-2">
      <span className="text-xs text-asos-text-secondary">{label}</span>
      <div className="flex items-center gap-2">
        {detail && <span className="text-[10px] text-asos-text-muted">{detail}</span>}
        <div className={`w-2 h-2 rounded-full ${active ? 'bg-green-500' : 'bg-zinc-600'}`} />
      </div>
    </div>
  );
}

function QuickAction({ icon: Icon, label, onClick, loading }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-2 bg-asos-bg/30 hover:bg-asos-bg/50 rounded-lg px-4 py-3 text-sm transition text-left disabled:opacity-50"
    >
      {loading ? (
        <Loader2 size={16} className="animate-spin text-asos-accent flex-shrink-0" />
      ) : (
        <Icon size={16} className="text-asos-accent flex-shrink-0" />
      )}
      <span className="text-xs text-asos-text-secondary">{label}</span>
    </button>
  );
}
