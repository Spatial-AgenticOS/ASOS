import React, { useState, useEffect } from 'react';
import {
  Key, Sparkles, Eye, EyeOff, Shield, Zap, Database, Cpu, Volume2, User,
  Check, AlertCircle, Loader2, Save, RefreshCw, Trash2, Plus,
  Bluetooth, Wifi, WifiOff, Radio, Smartphone, Glasses, Watch, Bot,
} from 'lucide-react';

import { API_BASE as API } from '../config';

export default function Settings() {
  const [config, setConfig] = useState(null);
  const [identity, setIdentity] = useState(null);
  const [devices, setDevices] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [newSkillKey, setNewSkillKey] = useState({ id: '', key: '' });
  const [activeTab, setActiveTab] = useState('identity');

  useEffect(() => {
    fetch(`${API}/api/config`).then(r => r.json()).then(setConfig).catch(() => {});
    fetch(`${API}/api/identity`).then(r => r.json()).then(setIdentity).catch(() => {});
    fetch(`${API}/api/devices`).then(r => r.json()).then(d => setDevices(d.devices || [])).catch(() => {});
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
    flash();
  };

  const saveIdentity = async () => {
    if (!identity) return;
    setSaving(true);
    await fetch(`${API}/api/identity`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(identity),
    });
    setSaving(false);
    flash();
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
    flash();
  };

  const flash = () => {
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

  const tabs = [
    { id: 'identity', label: 'Identity', icon: User },
    { id: 'devices', label: 'Devices', icon: Bluetooth },
    { id: 'llm', label: 'AI Model', icon: Sparkles },
    { id: 'features', label: 'Features', icon: Zap },
    { id: 'keys', label: 'API Keys', icon: Key },
    { id: 'security', label: 'Security', icon: Shield },
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-4 lg:p-8 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl lg:text-2xl font-bold">Settings</h1>
            <p className="text-xs lg:text-sm text-gray-400 mt-1">Configure THEORA to your needs</p>
          </div>
          {saved && (
            <div className="flex items-center gap-2 text-green-400 text-sm animate-pulse">
              <Check size={14} /> Saved
            </div>
          )}
        </div>

        {/* Tab Navigation */}
        <div className="flex gap-1 overflow-x-auto pb-1 -mx-4 px-4 lg:mx-0 lg:px-0">
          {tabs.map(t => {
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs lg:text-sm font-medium whitespace-nowrap transition ${
                  activeTab === t.id
                    ? 'bg-asos-accent bg-opacity-15 text-asos-accent'
                    : 'text-gray-400 hover:text-white hover:bg-white hover:bg-opacity-5'
                }`}
              >
                <Icon size={14} />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Identity Tab */}
        {activeTab === 'identity' && identity && (
          <div className="space-y-5">
            <Section title="Agent Identity" icon={User}>
              <p className="text-xs text-gray-500 mb-4">
                Define who THEORA is. This shapes how it talks, thinks, and behaves.
                Stored at <code className="bg-black px-1.5 py-0.5 rounded font-mono text-[10px]">~/.theora/identity.yaml</code>
              </p>

              <div className="space-y-4">
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Agent Name</label>
                  <input
                    className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                    value={identity.name || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, name: e.target.value }))}
                    placeholder="THEORA"
                  />
                </div>

                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Tagline</label>
                  <input
                    className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                    value={identity.tagline || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, tagline: e.target.value }))}
                    placeholder="Your personal AI operating system"
                  />
                </div>

                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Personality</label>
                  <textarea
                    rows={5}
                    className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent resize-none"
                    value={identity.personality || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, personality: e.target.value }))}
                    placeholder="Describe how THEORA should behave and communicate..."
                  />
                </div>

                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Rules (one per line)</label>
                  <textarea
                    rows={4}
                    className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent resize-none font-mono"
                    value={(identity.rules || []).join('\n')}
                    onChange={e => setIdentity(prev => ({ ...prev, rules: e.target.value.split('\n').filter(r => r.trim()) }))}
                    placeholder="Never make up sensor data&#10;Keep responses concise&#10;Always include units for health data"
                  />
                </div>

                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Communication Style</label>
                  <textarea
                    rows={3}
                    className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent resize-none"
                    value={identity.greeting_style || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, greeting_style: e.target.value }))}
                    placeholder="How should THEORA greet and communicate..."
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-gray-400 mb-1 block">TTS Voice</label>
                    <select
                      className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                      value={identity.voice?.tts_voice || 'nova'}
                      onChange={e => setIdentity(prev => ({ ...prev, voice: { ...(prev.voice || {}), tts_voice: e.target.value } }))}
                    >
                      {['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'].map(v => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-gray-400 mb-1 block">Style</label>
                    <select
                      className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                      value={identity.voice?.style || 'conversational'}
                      onChange={e => setIdentity(prev => ({ ...prev, voice: { ...(prev.voice || {}), style: e.target.value } }))}
                    >
                      {['conversational', 'professional', 'friendly', 'technical'].map(v => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <button
                  onClick={saveIdentity}
                  disabled={saving}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-asos-accent text-white rounded-lg font-medium hover:bg-opacity-90 transition active:scale-[0.98] disabled:opacity-50"
                >
                  {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  Save Identity
                </button>
              </div>
            </Section>
          </div>
        )}

        {/* Devices Tab */}
        {activeTab === 'devices' && (
          <div className="space-y-5">
            <Section title="Connected Devices" icon={Bluetooth}>
              <p className="text-xs text-gray-500 mb-4">
                Hardware nodes connected to the THEORA Brain via WebSocket.
                Any device running a THEORA daemon can connect — phones, glasses, wristbands, robots.
              </p>

              {devices.length === 0 ? (
                <div className="text-center py-8 bg-black bg-opacity-30 rounded-xl border border-dashed border-asos-border">
                  <Radio size={32} className="mx-auto opacity-20 mb-3" />
                  <p className="text-sm text-gray-400">No devices connected</p>
                  <p className="text-xs text-gray-500 mt-2 max-w-xs mx-auto">
                    Devices connect automatically when they run a THEORA daemon.
                    Check the docs for how to set up a new node.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {devices.map(dev => (
                    <DeviceCard key={dev.node_id} device={dev} />
                  ))}
                </div>
              )}
            </Section>

            <Section title="How to Connect Devices" icon={Wifi}>
              <div className="space-y-3 text-sm">
                {[
                  { icon: Smartphone, name: 'Phone (iOS/Android)', desc: 'Run the THEORA bridge app. It connects via WebSocket to your Brain server and streams audio, health data, and sensors.' },
                  { icon: Glasses, name: 'Smart Glasses', desc: 'Any BLE-capable glasses can connect through the phone bridge or a direct daemon. The glasses stream camera frames and mic audio.' },
                  { icon: Watch, name: 'Wristband / Watch', desc: 'Health sensors (HR, SpO2, temp) connect via BLE through a phone bridge or dedicated USB dongle daemon.' },
                  { icon: Bot, name: 'Robot / Custom Hardware', desc: 'Any device running Python or Kotlin can use the node SDK. Connect to ws://BRAIN_IP:9090/v1/node with your API key.' },
                ].map(item => (
                  <div key={item.name} className="flex gap-3 bg-black bg-opacity-30 rounded-lg p-3 border border-asos-border">
                    <item.icon size={20} className="text-asos-accent flex-shrink-0 mt-0.5" />
                    <div>
                      <div className="font-medium text-sm">{item.name}</div>
                      <div className="text-xs text-gray-400 mt-0.5">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-4 bg-black border border-asos-border rounded-lg p-3">
                <label className="text-xs text-gray-400 mb-1 block">Brain Address (for devices to connect)</label>
                <code className="text-sm text-asos-accent font-mono">
                  ws://{window.location.hostname}:9090/v1/node?api_key=dev-secret-key
                </code>
              </div>
            </Section>
          </div>
        )}

        {/* LLM Tab */}
        {activeTab === 'llm' && (
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
        )}

        {/* Features Tab */}
        {activeTab === 'features' && (
          <div className="space-y-5">
            <Section title="Features" icon={Zap}>
              <div className="space-y-3">
                <Toggle label="Streaming Responses" desc="Token-by-token LLM output in real-time" value={config.features?.streaming} onChange={v => updateSetting('features', 'streaming', v)} />
                <Toggle label="Proactive Agent" desc="Autonomous health and device alerts" value={config.features?.proactive} onChange={v => updateSetting('features', 'proactive', v)} />
                <Toggle label="Self-Learning" desc="Extract knowledge from conversations" value={config.features?.self_learning ?? true} onChange={v => updateSetting('features', 'self_learning', v)} />
              </div>
            </Section>

            <Section title="Vision" icon={Eye}>
              <div className="space-y-3">
                <Toggle label="Vision Pipeline" desc="Process camera frames from connected devices" value={config.vision?.enabled} onChange={v => updateSetting('vision', 'enabled', v)} />
              </div>
            </Section>

            <Section title="Audio" icon={Volume2}>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">TTS Voice</label>
                  <select
                    className="w-full bg-black border border-asos-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent"
                    value={config.audio?.tts_voice || 'nova'}
                    onChange={e => updateSetting('audio', 'tts_voice', e.target.value)}
                  >
                    {['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'].map(v => <option key={v} value={v}>{v}</option>)}
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
          </div>
        )}

        {/* API Keys Tab */}
        {activeTab === 'keys' && (
          <Section title="Skill API Keys" icon={Key}>
            <div className="space-y-3">
              {config.has_skill_keys?.map(id => (
                <div key={id} className="flex items-center justify-between bg-black bg-opacity-30 rounded-lg px-4 py-3">
                  <span className="text-sm font-mono">{id}</span>
                  <span className="text-xs text-green-400 flex items-center gap-1"><Check size={12} /> Configured</span>
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
        )}

        {/* Security Tab */}
        {activeTab === 'security' && (
          <div className="space-y-5">
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

            <Section title="Memory" icon={Database}>
              <p className="text-sm text-gray-400">
                Memory data stored at <code className="text-xs bg-black px-2 py-1 rounded font-mono">~/.theora/memory.db</code>
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
        )}
      </div>
    </div>
  );
}

function DeviceCard({ device }) {
  const typeIcons = {
    'glasses': Glasses,
    'phone': Smartphone,
    'wristband': Watch,
    'robot': Bot,
  };
  const Icon = typeIcons[device.type] || Radio;

  return (
    <div className={`flex items-center gap-3 bg-asos-card border rounded-xl px-4 py-3 ${
      device.connected ? 'border-green-500 border-opacity-30' : 'border-asos-border'
    }`}>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
        device.connected ? 'bg-green-500 bg-opacity-10' : 'bg-white bg-opacity-5'
      }`}>
        <Icon size={20} className={device.connected ? 'text-green-400' : 'text-gray-500'} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm truncate">{device.node_id}</div>
        <div className="text-xs text-gray-400">{device.type || 'unknown device'}</div>
      </div>
      <div className={`w-2.5 h-2.5 rounded-full ${device.connected ? 'bg-green-500' : 'bg-gray-600'}`} />
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
