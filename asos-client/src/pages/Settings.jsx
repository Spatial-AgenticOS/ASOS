import React, { useState, useEffect } from 'react';
import {
  Key, Sparkles, Eye, EyeOff, Shield, Zap, Database, Cpu, Volume2,
  Check, AlertCircle, Loader2, Save, RefreshCw, Trash2, Plus,
} from 'lucide-react';

const API = 'http://localhost:9090';

export default function Settings() {
  const [config, setConfig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [newSkillKey, setNewSkillKey] = useState({ id: '', key: '' });

  useEffect(() => {
    fetch(`${API}/api/config`).then(r => r.json()).then(setConfig).catch(() => {});
  }, []);

  const updateSetting = async (section, key, value) => {
    setConfig(prev => ({
      ...prev,
      [section]: { ...(prev?.[section] || {}), [key]: value },
    }));
    await fetch(`${API}/api/config/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section, key, value }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const saveSkillKey = async () => {
    if (!newSkillKey.id || !newSkillKey.key) return;
    await fetch(`${API}/api/config/credentials`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_keys: { [newSkillKey.id]: newSkillKey.key } }),
    });
    setNewSkillKey({ id: '', key: '' });
    const resp = await fetch(`${API}/api/config`);
    setConfig(await resp.json());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  if (!config) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 border-2 border-asos-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 lg:p-8 space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Settings</h1>
            <p className="text-sm text-gray-400 mt-1">Configure THEORA to your needs</p>
          </div>
          {saved && (
            <div className="flex items-center gap-2 text-green-400 text-sm animate-pulse">
              <Check size={14} /> Saved
            </div>
          )}
        </div>

        {/* LLM Configuration */}
        <Section title="LLM Provider" icon={Sparkles}>
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              {['openai', 'groq', 'ollama'].map(p => (
                <button
                  key={p}
                  onClick={() => updateSetting('llm', 'provider', p)}
                  className={`px-4 py-3 rounded-lg border text-sm font-medium transition ${
                    config.llm?.provider === p
                      ? 'border-asos-accent bg-asos-accent bg-opacity-10 text-asos-accent'
                      : 'border-asos-border bg-asos-card hover:border-gray-600'
                  }`}
                >
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </button>
              ))}
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Model</label>
              <input
                className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
                value={config.llm?.model || ''}
                onChange={e => updateSetting('llm', 'model', e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Base URL (leave blank for defaults)</label>
              <input
                className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
                placeholder="https://api.openai.com/v1"
                value={config.llm?.base_url || ''}
                onChange={e => updateSetting('llm', 'base_url', e.target.value)}
              />
            </div>
          </div>
        </Section>

        {/* Features */}
        <Section title="Features" icon={Zap}>
          <div className="space-y-3">
            <Toggle
              label="Streaming Responses"
              desc="Token-by-token LLM output in real-time"
              value={config.features?.streaming}
              onChange={v => updateSetting('features', 'streaming', v)}
            />
            <Toggle
              label="Proactive Agent"
              desc="Autonomous health and device alerts"
              value={config.features?.proactive}
              onChange={v => updateSetting('features', 'proactive', v)}
            />
            <Toggle
              label="Self-Learning"
              desc="Extract knowledge from conversations"
              value={config.features?.self_learning ?? true}
              onChange={v => updateSetting('features', 'self_learning', v)}
            />
          </div>
        </Section>

        {/* Vision */}
        <Section title="Vision" icon={Eye}>
          <div className="space-y-3">
            <Toggle
              label="Vision Pipeline"
              desc="Process camera frames from connected glasses"
              value={config.vision?.enabled}
              onChange={v => updateSetting('vision', 'enabled', v)}
            />
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Max Frame Size (KB)</label>
              <input
                type="number"
                className="w-32 bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                value={config.vision?.max_frame_kb || 512}
                onChange={e => updateSetting('vision', 'max_frame_kb', parseInt(e.target.value) || 512)}
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Scene Analysis Cooldown (seconds)</label>
              <input
                type="number"
                className="w-32 bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                value={config.vision?.scene_cooldown || 10}
                onChange={e => updateSetting('vision', 'scene_cooldown', parseInt(e.target.value) || 10)}
              />
            </div>
          </div>
        </Section>

        {/* Audio */}
        <Section title="Audio" icon={Volume2}>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-400 mb-1 block">TTS Voice</label>
              <select
                className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                value={config.audio?.tts_voice || 'nova'}
                onChange={e => updateSetting('audio', 'tts_voice', e.target.value)}
              >
                {['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'].map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">STT Model</label>
              <input
                className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
                value={config.audio?.stt_model || 'whisper-1'}
                onChange={e => updateSetting('audio', 'stt_model', e.target.value)}
              />
            </div>
          </div>
        </Section>

        {/* Skill Keys */}
        <Section title="Skill API Keys" icon={Key}>
          <div className="space-y-3">
            {config.has_skill_keys?.map(id => (
              <div key={id} className="flex items-center justify-between bg-black bg-opacity-30 rounded-lg px-4 py-3">
                <span className="text-sm font-mono">{id}</span>
                <span className="text-xs text-green-400 flex items-center gap-1">
                  <Check size={12} /> Configured
                </span>
              </div>
            ))}

            <div className="flex items-center gap-2 pt-2">
              <input
                placeholder="skill_id"
                className="flex-1 bg-black border border-asos-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
                value={newSkillKey.id}
                onChange={e => setNewSkillKey(prev => ({ ...prev, id: e.target.value }))}
              />
              <input
                type="password"
                placeholder="API key"
                className="flex-1 bg-black border border-asos-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
                value={newSkillKey.key}
                onChange={e => setNewSkillKey(prev => ({ ...prev, key: e.target.value }))}
              />
              <button
                onClick={saveSkillKey}
                disabled={!newSkillKey.id || !newSkillKey.key}
                className="px-3 py-2 bg-asos-accent rounded-lg text-sm hover:bg-opacity-80 disabled:opacity-30 transition"
              >
                <Plus size={16} />
              </button>
            </div>
          </div>
        </Section>

        {/* Security */}
        <Section title="Security" icon={Shield}>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Node API Key</label>
            <input
              type="password"
              className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
              value={config.security?.node_api_key || ''}
              onChange={e => updateSetting('security', 'node_api_key', e.target.value)}
            />
            <p className="text-xs text-gray-500 mt-1">Used to authenticate hardware daemon connections</p>
          </div>
        </Section>

        {/* Memory */}
        <Section title="Memory" icon={Database}>
          <p className="text-sm text-gray-400">
            Memory data is stored at <code className="text-xs bg-black px-2 py-1 rounded font-mono">~/.theora/memory.db</code>
          </p>
          <div className="flex gap-3 mt-3">
            <button className="flex items-center gap-2 px-4 py-2 bg-asos-card border border-asos-border rounded-lg text-sm hover:bg-opacity-80 transition">
              <Database size={14} /> Export
            </button>
            <button className="flex items-center gap-2 px-4 py-2 bg-red-900 bg-opacity-30 border border-red-800 rounded-lg text-sm text-red-400 hover:bg-opacity-50 transition">
              <Trash2 size={14} /> Clear All
            </button>
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, icon: Icon, children }) {
  return (
    <div className="bg-asos-card border border-asos-border rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Icon size={18} className="text-asos-accent" />
        <h2 className="font-semibold">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function Toggle({ label, desc, value, onChange }) {
  return (
    <div className="flex items-center justify-between py-1">
      <div>
        <div className="text-sm font-medium">{label}</div>
        {desc && <div className="text-xs text-gray-400 mt-0.5">{desc}</div>}
      </div>
      <button
        onClick={() => onChange(!value)}
        className={`w-12 h-7 rounded-full transition-all flex items-center px-1 ${
          value ? 'bg-asos-accent justify-end' : 'bg-gray-700 justify-start'
        }`}
      >
        <div className="w-5 h-5 bg-white rounded-full shadow transition-all" />
      </button>
    </div>
  );
}
