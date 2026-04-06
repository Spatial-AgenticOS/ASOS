import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain, Key, Puzzle, Cpu, ChevronRight, ChevronLeft,
  Check, AlertCircle, Loader2, Eye, EyeOff, Sparkles,
  Wifi, WifiOff, Shield, Zap, Link2, Music, Home, FileText,
  ExternalLink, Server,
} from 'lucide-react';

import { API_BASE as API } from '../config';

const STEPS = [
  { id: 'welcome', label: 'Welcome', icon: Brain },
  { id: 'llm', label: 'LLM Provider', icon: Sparkles },
  { id: 'keys', label: 'API Keys', icon: Key },
  { id: 'skills', label: 'Skills', icon: Puzzle },
  { id: 'apps', label: 'Connect Apps', icon: Link2 },
  { id: 'features', label: 'Features', icon: Zap },
  { id: 'finish', label: 'Launch', icon: Check },
];

export default function SetupWizard({ onComplete }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [config, setConfig] = useState(null);
  const [credentials, setCredentials] = useState({});
  const [settings, setSettings] = useState({});
  const [keyValid, setKeyValid] = useState(null);
  const [validating, setValidating] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/config`).then(r => r.json()).then(setConfig).catch(() => {});
  }, []);

  const validateKey = async () => {
    const provider = settings.llm?.provider || 'openai';
    const key = credentials.OPENAI_API_KEY || credentials.GROQ_API_KEY || '';
    if (!key && provider !== 'ollama') return;

    setValidating(true);
    try {
      const resp = await fetch(`${API}/api/config/validate-key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          api_key: key,
          base_url: settings.llm?.base_url || '',
        }),
      });
      const data = await resp.json();
      setKeyValid(data.valid);
    } catch {
      setKeyValid(false);
    }
    setValidating(false);
  };

  const handleFinish = async () => {
    setSaving(true);
    try {
      await fetch(`${API}/api/setup/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings, credentials }),
      });
      onComplete?.();
      navigate('/');
    } catch (e) {
      console.error('Setup failed:', e);
    }
    setSaving(false);
  };

  const updateSetting = (section, key, value) => {
    setSettings(prev => ({
      ...prev,
      [section]: { ...(prev[section] || {}), [key]: value },
    }));
  };

  const currentStep = STEPS[step];

  return (
    <div className="min-h-screen bg-black flex">
      {/* Left Panel — Steps */}
      <div className="hidden lg:flex w-72 bg-asos-card border-r border-asos-border flex-col py-8 px-6">
        <div className="flex items-center gap-3 mb-12">
          <Brain size={28} className="text-asos-accent" />
          <span className="text-lg font-bold tracking-wider">THEORA</span>
        </div>

        <div className="space-y-2">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const isActive = i === step;
            const isDone = i < step;
            return (
              <div
                key={s.id}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                  isActive ? 'bg-asos-accent bg-opacity-15 text-asos-accent' :
                  isDone ? 'text-green-400 opacity-70' : 'text-gray-500'
                }`}
              >
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                  isActive ? 'bg-asos-accent text-white' :
                  isDone ? 'bg-green-500 bg-opacity-20 text-green-400' :
                  'bg-white bg-opacity-5'
                }`}>
                  {isDone ? <Check size={14} /> : i + 1}
                </div>
                <span className="text-sm font-medium">{s.label}</span>
              </div>
            );
          })}
        </div>

        <div className="mt-auto pt-8 text-xs opacity-30">
          THEORA v1.0.0
        </div>
      </div>

      {/* Right Panel — Content */}
      <div className="flex-1 flex flex-col">
        {/* Mobile step indicator */}
        <div className="lg:hidden flex items-center gap-2 p-4 border-b border-asos-border">
          {STEPS.map((_, i) => (
            <div key={i} className={`h-1.5 flex-1 rounded-full ${i <= step ? 'bg-asos-accent' : 'bg-asos-border'}`} />
          ))}
        </div>

        <div className="flex-1 flex items-center justify-center p-8">
          <div className="w-full max-w-lg">
            {/* Step: Welcome */}
            {currentStep.id === 'welcome' && (
              <div className="text-center space-y-6">
                <div className="w-20 h-20 rounded-full bg-asos-accent bg-opacity-15 flex items-center justify-center mx-auto">
                  <Brain size={40} className="text-asos-accent" />
                </div>
                <h1 className="text-3xl font-bold">Welcome to THEORA</h1>
                <p className="text-gray-400 text-lg leading-relaxed max-w-md mx-auto">
                  The Spatial Agentic Operating System. Local-first intelligence
                  that sees, hears, learns, and acts.
                </p>
                <div className="grid grid-cols-2 gap-3 pt-4 text-sm">
                  {[
                    { icon: Sparkles, text: 'Self-Learning AI' },
                    { icon: Eye, text: 'Vision + Scene' },
                    { icon: Shield, text: 'Graduated Safety' },
                    { icon: Cpu, text: 'Hardware Nodes' },
                  ].map(({ icon: I, text }) => (
                    <div key={text} className="flex items-center gap-2 bg-asos-card rounded-lg p-3 border border-asos-border">
                      <I size={16} className="text-asos-accent" />
                      <span className="opacity-80">{text}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Step: LLM Provider */}
            {currentStep.id === 'llm' && (
              <div className="space-y-6">
                <h2 className="text-2xl font-bold">Choose Your LLM</h2>
                <p className="text-gray-400">THEORA needs a language model to think. Pick your provider.</p>
                <div className="space-y-3">
                  {[
                    { id: 'openai', name: 'OpenAI', desc: 'GPT-4o, GPT-4o-mini (cloud)', badge: 'Recommended' },
                    { id: 'groq', name: 'Groq', desc: 'LPU-accelerated Llama, Mixtral (cloud)' },
                    { id: 'ollama', name: 'Ollama', desc: 'Local models — fully private, no API key needed', badge: 'Private' },
                  ].map(p => (
                    <button
                      key={p.id}
                      onClick={() => updateSetting('llm', 'provider', p.id)}
                      className={`w-full text-left px-5 py-4 rounded-xl border transition-all ${
                        (settings.llm?.provider || 'openai') === p.id
                          ? 'border-asos-accent bg-asos-accent bg-opacity-10'
                          : 'border-asos-border bg-asos-card hover:border-gray-600'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-semibold">{p.name}</div>
                          <div className="text-sm text-gray-400 mt-0.5">{p.desc}</div>
                        </div>
                        {p.badge && (
                          <span className="text-xs px-2 py-1 rounded-full bg-asos-accent bg-opacity-20 text-asos-accent">
                            {p.badge}
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>

                {(settings.llm?.provider || 'openai') !== 'ollama' && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Model</label>
                    <select
                      className="w-full bg-asos-card border border-asos-border rounded-lg px-4 py-3 focus:outline-none focus:ring-1 focus:ring-asos-accent"
                      value={settings.llm?.model || 'gpt-4o-mini'}
                      onChange={e => updateSetting('llm', 'model', e.target.value)}
                    >
                      {(settings.llm?.provider || 'openai') === 'openai'
                        ? ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1-mini', 'gpt-4.1-nano'].map(m => <option key={m} value={m}>{m}</option>)
                        : ['llama-3.3-70b-versatile', 'mixtral-8x7b-32768'].map(m => <option key={m} value={m}>{m}</option>)
                      }
                    </select>
                  </div>
                )}
              </div>
            )}

            {/* Step: API Keys */}
            {currentStep.id === 'keys' && (
              <div className="space-y-6">
                <h2 className="text-2xl font-bold">API Keys</h2>
                <p className="text-gray-400">
                  {(settings.llm?.provider || 'openai') === 'ollama'
                    ? 'Ollama runs locally — no API key needed. You can add skill keys below.'
                    : 'Enter your API key. It\'s stored locally and never leaves your machine.'
                  }
                </p>

                {(settings.llm?.provider || 'openai') !== 'ollama' && (
                  <div className="space-y-3">
                    <label className="text-sm font-medium flex items-center gap-2">
                      <Key size={14} className="text-asos-accent" />
                      {(settings.llm?.provider || 'openai') === 'openai' ? 'OpenAI' : 'Groq'} API Key
                    </label>
                    <div className="relative">
                      <input
                        type={showKey ? 'text' : 'password'}
                        placeholder="sk-..."
                        className="w-full bg-asos-card border border-asos-border rounded-lg px-4 py-3 pr-20 focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono text-sm"
                        value={credentials[(settings.llm?.provider || 'openai') === 'openai' ? 'OPENAI_API_KEY' : 'GROQ_API_KEY'] || ''}
                        onChange={e => {
                          const keyName = (settings.llm?.provider || 'openai') === 'openai' ? 'OPENAI_API_KEY' : 'GROQ_API_KEY';
                          setCredentials(prev => ({ ...prev, [keyName]: e.target.value }));
                          setKeyValid(null);
                        }}
                      />
                      <button
                        onClick={() => setShowKey(!showKey)}
                        className="absolute right-12 top-1/2 -translate-y-1/2 p-1 opacity-40 hover:opacity-80"
                      >
                        {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                      <button
                        onClick={validateKey}
                        disabled={validating}
                        className="absolute right-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-asos-accent rounded text-xs font-medium hover:bg-opacity-80"
                      >
                        {validating ? <Loader2 size={14} className="animate-spin" /> : 'Test'}
                      </button>
                    </div>
                    {keyValid === true && (
                      <div className="flex items-center gap-2 text-green-400 text-sm">
                        <Check size={14} /> Key is valid
                      </div>
                    )}
                    {keyValid === false && (
                      <div className="flex items-center gap-2 text-red-400 text-sm">
                        <AlertCircle size={14} /> Key is invalid or expired
                      </div>
                    )}
                  </div>
                )}

                <div className="border-t border-asos-border pt-4 space-y-3">
                  <label className="text-sm font-medium opacity-60">Skill API Keys (optional)</label>
                  <p className="text-xs text-gray-500">Add keys for external services like weather, search, etc.</p>
                  {['web_search', 'spotify_music', 'messaging_sms', 'calendar_google'].map(skill => (
                    <div key={skill} className="flex items-center gap-2">
                      <span className="text-xs w-32 text-gray-400 truncate">{skill}</span>
                      <input
                        type="password"
                        placeholder="API key..."
                        className="flex-1 bg-asos-card border border-asos-border rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-asos-accent font-mono"
                        value={credentials.skill_keys?.[skill] || ''}
                        onChange={e => setCredentials(prev => ({
                          ...prev,
                          skill_keys: { ...(prev.skill_keys || {}), [skill]: e.target.value },
                        }))}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Step: Skills */}
            {currentStep.id === 'skills' && (
              <div className="space-y-6">
                <h2 className="text-2xl font-bold">Skills</h2>
                <p className="text-gray-400">
                  Skills are API-backed capabilities THEORA can use. Toggle which ones to enable.
                </p>
                <SkillsList />
              </div>
            )}

            {/* Step: Connect Apps */}
            {currentStep.id === 'apps' && (
              <div className="space-y-6">
                <h2 className="text-2xl font-bold">Connect Apps</h2>
                <p className="text-gray-400">
                  Link your favorite services. OAuth for Spotify & Notion, API token for Home Assistant.
                </p>

                <div className="space-y-3">
                  <AppConnectCard
                    icon={Music}
                    name="Spotify"
                    desc="Control music playback, search, queue tracks"
                    providerId="spotify"
                    authType="oauth"
                  />
                  <AppConnectCard
                    icon={Home}
                    name="Home Assistant"
                    desc="Control lights, sensors, automations"
                    providerId="home_assistant"
                    authType="token"
                    onTokenSave={(token) => {
                      fetch(`${API}/api/integrations/token`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ provider_id: 'home_assistant', token }),
                      });
                    }}
                  />
                  <AppConnectCard
                    icon={FileText}
                    name="Notion"
                    desc="Read and write pages, query databases"
                    providerId="notion"
                    authType="oauth"
                  />
                </div>

                <div className="border-t border-asos-border pt-4">
                  <h3 className="text-sm font-medium opacity-60 mb-3 flex items-center gap-2">
                    <Server size={14} /> MCP Servers (Advanced)
                  </h3>
                  <p className="text-xs text-gray-500 mb-3">
                    Connect MCP-compatible tools like GitHub, Slack, databases.
                    Configure these in Settings after setup.
                  </p>
                  <MCPServerList />
                </div>
              </div>
            )}

            {/* Step: Features */}
            {currentStep.id === 'features' && (
              <div className="space-y-6">
                <h2 className="text-2xl font-bold">Features</h2>
                <p className="text-gray-400">Enable or disable advanced capabilities.</p>
                <div className="space-y-4">
                  {[
                    { key: 'streaming', label: 'Streaming Responses', desc: 'See LLM output token-by-token in real-time', section: 'features' },
                    { key: 'proactive', label: 'Proactive Agent', desc: 'Autonomous alerts on health anomalies and device status', section: 'features' },
                    { key: 'self_learning', label: 'Self-Learning', desc: 'Extract knowledge from conversations and learn preferences', section: 'features' },
                    { key: 'enabled', label: 'Vision Pipeline', desc: 'Process camera frames from connected glasses', section: 'vision' },
                  ].map(f => (
                    <div key={f.key} className="flex items-center justify-between bg-asos-card border border-asos-border rounded-xl px-5 py-4">
                      <div>
                        <div className="font-medium text-sm">{f.label}</div>
                        <div className="text-xs text-gray-400 mt-0.5">{f.desc}</div>
                      </div>
                      <button
                        onClick={() => {
                          const current = settings[f.section]?.[f.key] ?? (f.key === 'self_learning');
                          updateSetting(f.section, f.key, !current);
                        }}
                        className={`w-12 h-7 rounded-full transition-all flex items-center px-1 ${
                          (settings[f.section]?.[f.key] ?? (f.key === 'self_learning'))
                            ? 'bg-asos-accent justify-end' : 'bg-gray-700 justify-start'
                        }`}
                      >
                        <div className="w-5 h-5 bg-white rounded-full shadow transition-all" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Step: Finish */}
            {currentStep.id === 'finish' && (
              <div className="text-center space-y-6">
                <div className="w-20 h-20 rounded-full bg-green-500 bg-opacity-15 flex items-center justify-center mx-auto">
                  <Check size={40} className="text-green-400" />
                </div>
                <h2 className="text-3xl font-bold">Ready to Launch</h2>
                <p className="text-gray-400 text-lg max-w-md mx-auto">
                  THEORA is configured and ready. You can always change settings later.
                </p>
                <div className="bg-asos-card border border-asos-border rounded-xl p-5 text-left space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Provider</span>
                    <span className="font-mono">{settings.llm?.provider || 'openai'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Model</span>
                    <span className="font-mono">{settings.llm?.model || 'gpt-4o-mini'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Streaming</span>
                    <span>{settings.features?.streaming ? 'On' : 'Off'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Self-Learning</span>
                    <span>{(settings.features?.self_learning ?? true) ? 'On' : 'Off'}</span>
                  </div>
                </div>
                <button
                  onClick={handleFinish}
                  disabled={saving}
                  className="px-8 py-4 bg-asos-accent text-white rounded-xl font-bold text-lg hover:bg-opacity-90 transition-all active:scale-95 disabled:opacity-50 flex items-center gap-3 mx-auto"
                >
                  {saving ? <Loader2 size={20} className="animate-spin" /> : <Sparkles size={20} />}
                  Launch THEORA
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between p-6 border-t border-asos-border">
          <button
            onClick={() => setStep(s => Math.max(0, s - 1))}
            disabled={step === 0}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm text-gray-400 hover:text-white disabled:opacity-20 transition"
          >
            <ChevronLeft size={16} /> Back
          </button>
          <div className="text-xs opacity-30">
            {step + 1} / {STEPS.length}
          </div>
          {step < STEPS.length - 1 && (
            <button
              onClick={() => setStep(s => Math.min(STEPS.length - 1, s + 1))}
              className="flex items-center gap-2 px-5 py-2.5 bg-asos-accent text-white rounded-lg text-sm font-medium hover:bg-opacity-90 transition active:scale-95"
            >
              Next <ChevronRight size={16} />
            </button>
          )}
          {step === STEPS.length - 1 && <div />}
        </div>
      </div>
    </div>
  );
}

function AppConnectCard({ icon: Icon, name, desc, providerId, authType, onTokenSave }) {
  const [connected, setConnected] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/integrations`).then(r => r.json()).then(data => {
      const key = `${providerId}_connected`;
      setConnected(data[key] || false);
    }).catch(() => {});
  }, [providerId]);

  const handleOAuth = async () => {
    const resp = await fetch(`${API}/api/oauth/authorize/${providerId}`);
    const data = await resp.json();
    if (data.url) window.open(data.url, '_blank');
  };

  const handleTokenSave = () => {
    if (tokenInput && onTokenSave) {
      onTokenSave(tokenInput);
      setConnected(true);
      setTokenInput('');
    }
  };

  return (
    <div className={`bg-asos-card border rounded-xl px-5 py-4 transition-all ${
      connected ? 'border-green-500 border-opacity-40' : 'border-asos-border'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
            connected ? 'bg-green-500 bg-opacity-15' : 'bg-white bg-opacity-5'
          }`}>
            <Icon size={20} className={connected ? 'text-green-400' : 'text-gray-400'} />
          </div>
          <div>
            <div className="font-medium text-sm">{name}</div>
            <div className="text-xs text-gray-400">{desc}</div>
          </div>
        </div>
        {connected ? (
          <span className="text-xs px-2 py-1 rounded-full bg-green-500 bg-opacity-20 text-green-400">Connected</span>
        ) : authType === 'oauth' ? (
          <button
            onClick={handleOAuth}
            className="flex items-center gap-1 px-3 py-1.5 bg-asos-accent bg-opacity-15 text-asos-accent text-xs rounded-lg hover:bg-opacity-25 transition"
          >
            <ExternalLink size={12} /> Connect
          </button>
        ) : null}
      </div>
      {authType === 'token' && !connected && (
        <div className="mt-3 flex gap-2">
          <input
            type={showToken ? 'text' : 'password'}
            placeholder="Long-lived access token..."
            className="flex-1 bg-black border border-asos-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-asos-accent"
            value={tokenInput}
            onChange={e => setTokenInput(e.target.value)}
          />
          <button
            onClick={handleTokenSave}
            disabled={!tokenInput}
            className="px-3 py-2 bg-asos-accent text-white text-xs rounded hover:bg-opacity-90 disabled:opacity-30"
          >
            Save
          </button>
        </div>
      )}
    </div>
  );
}

function MCPServerList() {
  const [servers, setServers] = useState([]);
  useEffect(() => {
    fetch(`${API}/api/mcp/registry`).then(r => r.json()).then(data => {
      setServers(data.servers || []);
    }).catch(() => {});
  }, []);

  if (!servers.length) {
    return (
      <div className="text-xs text-gray-500 bg-asos-card border border-asos-border rounded-lg p-4">
        MCP servers will be available after setup. Common servers: GitHub, Slack, PostgreSQL, Browser.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2">
      {servers.slice(0, 6).map(s => (
        <div key={s.id} className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs ${
          s.installed ? 'border-asos-border' : 'border-asos-border opacity-50'
        }`}>
          <Server size={12} className={s.installed ? 'text-asos-accent' : 'text-gray-500'} />
          <span>{s.name}</span>
          {s.installed && <Check size={10} className="text-green-400 ml-auto" />}
        </div>
      ))}
    </div>
  );
}

function SkillsList() {
  const [skills, setSkills] = useState([]);
  useEffect(() => {
    fetch(`${API}/skills`).then(r => r.json()).then(setSkills).catch(() => {});
  }, []);

  if (!skills.length) {
    return (
      <div className="bg-asos-card border border-asos-border rounded-xl p-6 text-center">
        <Puzzle size={32} className="mx-auto opacity-30 mb-3" />
        <p className="text-sm opacity-50">No skills loaded yet. Skills will appear when the brain starts.</p>
        <p className="text-xs opacity-30 mt-1">Add JSON manifests to ~/.theora/skills/ or asos-core/skills/manifests/</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {skills.map(s => (
        <div key={s.skill_id} className="flex items-center justify-between bg-asos-card border border-asos-border rounded-xl px-5 py-4">
          <div>
            <div className="font-medium text-sm">{s.name}</div>
            <div className="text-xs text-gray-400">{s.description}</div>
            <div className="text-xs text-gray-500 mt-1">{s.endpoints} endpoint{s.endpoints !== 1 ? 's' : ''}</div>
          </div>
          <div className="w-12 h-7 rounded-full bg-asos-accent flex items-center justify-end px-1">
            <div className="w-5 h-5 bg-white rounded-full shadow" />
          </div>
        </div>
      ))}
    </div>
  );
}
