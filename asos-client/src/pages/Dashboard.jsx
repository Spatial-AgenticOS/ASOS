import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain, Cpu, Activity, Database, MessageSquare, Puzzle,
  Wifi, WifiOff, Zap, Eye, Shield, BookOpen, Clock, TrendingUp,
} from 'lucide-react';

const API = 'http://localhost:9090';

export default function Dashboard() {
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = () => {
    fetch(`${API}/api/system/info`)
      .then(r => r.json())
      .then(data => { setInfo(data); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 5000);
    return () => clearInterval(iv);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 border-2 border-asos-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!info) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <WifiOff size={40} className="opacity-30" />
        <p className="text-sm opacity-50">Cannot connect to THEORA Brain</p>
        <button onClick={refresh} className="px-4 py-2 bg-asos-card border border-asos-border rounded-lg text-sm hover:bg-opacity-80">
          Retry
        </button>
      </div>
    );
  }

  const mem = info.memory || {};
  const config = info.config || {};

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 lg:p-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Dashboard</h1>
            <p className="text-sm text-gray-400 mt-1">THEORA Brain v{info.version}</p>
          </div>
          <button
            onClick={() => navigate('/chat')}
            className="flex items-center gap-2 px-5 py-2.5 bg-asos-accent text-white rounded-lg text-sm font-medium hover:bg-opacity-90 transition active:scale-95"
          >
            <MessageSquare size={16} /> Open Chat
          </button>
        </div>

        {/* Status Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatusCard
            icon={Wifi}
            label="Sessions"
            value={info.sessions}
            color="#00b894"
          />
          <StatusCard
            icon={Cpu}
            label="Nodes"
            value={info.nodes?.length || 0}
            subtitle={info.nodes?.length ? info.nodes.join(', ') : 'none'}
            color="#6c5ce7"
          />
          <StatusCard
            icon={Puzzle}
            label="Skills"
            value={info.skills?.length || 0}
            color="#fdcb6e"
          />
          <StatusCard
            icon={Activity}
            label="Audio"
            value={info.audio_available ? 'Ready' : 'Off'}
            color={info.audio_available ? '#55efc4' : '#636e72'}
          />
        </div>

        {/* Memory */}
        <div className="bg-asos-card border border-asos-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Database size={18} className="text-asos-accent" />
            <h2 className="font-semibold">Memory</h2>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <MemoryMetric label="Notes" value={mem.notes || 0} icon={BookOpen} />
            <MemoryMetric label="Episodes" value={mem.episodes || 0} icon={Clock} />
            <MemoryMetric label="Knowledge" value={mem.knowledge_triples || 0} icon={Brain} />
            <MemoryMetric label="Exec Logs" value={mem.execution_logs || 0} icon={TrendingUp} />
            <MemoryMetric label="Sessions" value={mem.active_working_sessions || 0} icon={Zap} />
          </div>
        </div>

        {/* Features */}
        <div className="bg-asos-card border border-asos-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Zap size={18} className="text-asos-accent" />
            <h2 className="font-semibold">Active Features</h2>
          </div>
          <div className="flex flex-wrap gap-3">
            <FeatureBadge label="Self-Learning" active={config.features?.self_learning} />
            <FeatureBadge label="Streaming" active={config.features?.streaming} />
            <FeatureBadge label="Proactive" active={config.features?.proactive} />
            <FeatureBadge label="Vision" active={config.vision?.enabled} />
            <FeatureBadge label="LLM Key" active={config.has_llm_key} />
          </div>
        </div>

        {/* Skills */}
        {info.skills && info.skills.length > 0 && (
          <div className="bg-asos-card border border-asos-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Puzzle size={18} className="text-asos-accent" />
              <h2 className="font-semibold">Loaded Skills</h2>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {info.skills.map(s => (
                <div key={s.skill_id} className="flex items-center justify-between bg-black bg-opacity-30 rounded-lg px-4 py-3">
                  <div>
                    <span className="text-sm font-medium">{s.name}</span>
                    <span className="text-xs text-gray-500 ml-2">{s.endpoints} endpoints</span>
                  </div>
                  <span className={`text-xs px-2 py-1 rounded-full ${
                    config.has_skill_keys?.includes(s.skill_id)
                      ? 'bg-green-500 bg-opacity-20 text-green-400'
                      : 'bg-gray-700 text-gray-400'
                  }`}>
                    {config.has_skill_keys?.includes(s.skill_id) ? 'Key Set' : 'No Key'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Connected Nodes */}
        {info.nodes && info.nodes.length > 0 && (
          <div className="bg-asos-card border border-asos-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <Cpu size={18} className="text-green-400" />
              <h2 className="font-semibold">Connected Nodes</h2>
            </div>
            <div className="space-y-2">
              {info.nodes.map(n => (
                <div key={n} className="flex items-center gap-3 bg-black bg-opacity-30 rounded-lg px-4 py-3">
                  <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_6px_#22c55e]" />
                  <span className="text-sm font-mono">{n}</span>
                </div>
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
        <Icon size={16} style={{ color }} />
        <span className="text-xs text-gray-400 uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-2xl font-bold" style={{ color }}>{value}</div>
      {subtitle && <div className="text-xs text-gray-500 mt-1 truncate">{subtitle}</div>}
    </div>
  );
}

function MemoryMetric({ label, value, icon: Icon }) {
  return (
    <div className="text-center">
      <Icon size={16} className="mx-auto opacity-40 mb-1" />
      <div className="text-xl font-bold">{value}</div>
      <div className="text-xs text-gray-400">{label}</div>
    </div>
  );
}

function FeatureBadge({ label, active }) {
  return (
    <span className={`text-xs px-3 py-1.5 rounded-full font-medium ${
      active
        ? 'bg-asos-accent bg-opacity-20 text-asos-accent'
        : 'bg-gray-800 text-gray-500'
    }`}>
      {active ? '●' : '○'} {label}
    </span>
  );
}
