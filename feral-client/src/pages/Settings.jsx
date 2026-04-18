import React, { useState, useEffect } from 'react';
import {
  Key, Sparkles, Eye, EyeOff, Shield, Zap, Database, Cpu, Volume2, User,
  Check, AlertCircle, Loader2, Save, RefreshCw, Trash2, Plus,
  Bluetooth, Wifi, WifiOff, Radio, Smartphone, Glasses, Watch, Bot,
  Sun, Moon, Clock, Play, Pause, ChevronDown, ChevronUp,
  MessageSquare, Server, ShoppingBag, Download, Search,
  ThumbsUp, ThumbsDown, Users, Webhook, Copy, Link,
} from 'lucide-react';

import { API_BASE as API } from '../config';
import { useTheme } from '../hooks/useTheme';
import { useToast } from '../components/Toast';

export default function Settings() {
  const { theme, toggle: toggleTheme } = useTheme();
  const { addToast } = useToast();
  const [config, setConfig] = useState(null);
  const [identity, setIdentity] = useState(null);
  const [devices, setDevices] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [newSkillKey, setNewSkillKey] = useState({ id: '', key: '' });
  const [activeTab, setActiveTab] = useState('identity');
  const [llmPresets, setLlmPresets] = useState([]);
  const [applyingPreset, setApplyingPreset] = useState('');
  const [presetFeedback, setPresetFeedback] = useState('');
  const [pendingSkills, setPendingSkills] = useState([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [pendingActionBusy, setPendingActionBusy] = useState('');
  const [routines, setRoutines] = useState([]);
  const [routinesLoading, setRoutinesLoading] = useState(false);
  const [expandedRoutine, setExpandedRoutine] = useState(null);
  const [routineRuns, setRoutineRuns] = useState({});
  const [newRoutine, setNewRoutine] = useState({ description: '', cron_expr: 'every 60m', prompt: '' });
  const [channelsConfig, setChannelsConfig] = useState({
    telegram: { enabled: false, bot_token: '' },
    discord: { enabled: false, bot_token: '' },
    slack: { enabled: false, bot_token: '', app_token: '' },
    whatsapp: { enabled: false, access_token: '', phone_number_id: '' },
  });
  const [channelStatus, setChannelStatus] = useState({});
  const [channelsSaving, setChannelsSaving] = useState(false);
  const [marketplaceSearch, setMarketplaceSearch] = useState('');
  const [marketplaceResults, setMarketplaceResults] = useState([]);
  const [installedSkills, setInstalledSkills] = useState([]);
  const [marketplaceLoading, setMarketplaceLoading] = useState(false);
  const [installingSkill, setInstallingSkill] = useState('');
  const [specialists, setSpecialists] = useState([]);
  const [spawnProposals, setSpawnProposals] = useState([]);
  const [specialistsLoading, setSpecialistsLoading] = useState(false);
  const [spawningId, setSpawningId] = useState('');
  const [feedbackBusy, setFeedbackBusy] = useState('');
  const [webhooks, setWebhooks] = useState([]);
  const [webhooksLoading, setWebhooksLoading] = useState(false);
  const [newWebhook, setNewWebhook] = useState({ name: '', secret: '', action: 'chat' });
  const [creatingWebhook, setCreatingWebhook] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState('');
  // Tool Genesis / Proposed Skills
  const [proposals, setProposals] = useState([]);
  const [proposalActionBusy, setProposalActionBusy] = useState('');
  // Marketplace subtabs
  const [marketplaceSubtab, setMarketplaceSubtab] = useState('skills');
  const [catalogItems, setCatalogItems] = useState({ skill: [], daemon: [], mcp: [] });
  const [catalogLoading, setCatalogLoading] = useState({ skill: false, daemon: false, mcp: false });
  const [catalogError, setCatalogError] = useState({ skill: false, daemon: false, mcp: false });
  const [installingItem, setInstallingItem] = useState('');

  const fetchWebhooks = async () => {
    setWebhooksLoading(true);
    try {
      const data = await fetch(`${API}/api/webhooks/list`).then(r => r.json());
      setWebhooks(data.webhooks || []);
    } catch { setWebhooks([]); }
    finally { setWebhooksLoading(false); }
  };

  const createWebhook = async () => {
    if (!newWebhook.name) return;
    setCreatingWebhook(true);
    try {
      await fetch(`${API}/api/webhooks/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newWebhook),
      });
      setNewWebhook({ name: '', secret: '', action: 'chat' });
      await fetchWebhooks();
      flash();
    } catch (e) { addToast(e.message || 'Failed to create webhook'); }
    finally { setCreatingWebhook(false); }
  };

  const deleteWebhook = async (webhookId) => {
    try {
      await fetch(`${API}/api/webhooks/${webhookId}`, { method: 'DELETE' });
      await fetchWebhooks();
    } catch (e) { addToast(e.message || 'Failed to delete webhook'); }
  };

  // ── Tool Genesis: Proposed Skills ──────────────────────────────────────
  const fetchProposals = async () => {
    try {
      const res = await fetch(`${API}/api/tool-genesis/pending`);
      if (!res.ok) { setProposals([]); return; }
      const data = await res.json();
      setProposals(data.proposals || []);
    } catch {
      setProposals([]);
    }
  };

  const approveProposal = async (toolId) => {
    setProposalActionBusy(`approve:${toolId}`);
    try {
      const res = await fetch(`${API}/api/tool-genesis/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_id: toolId }),
      });
      if (res.ok) {
        addToast('Skill approved and loaded');
        setProposals(prev => prev.filter(p => p.tool_id !== toolId));
      } else {
        addToast('Approve failed');
      }
    } catch (e) {
      addToast(e.message || 'Approve failed');
    } finally {
      setProposalActionBusy('');
    }
  };

  const rejectProposal = async (toolId) => {
    setProposalActionBusy(`reject:${toolId}`);
    try {
      const res = await fetch(`${API}/api/tool-genesis/${toolId}`, { method: 'DELETE' });
      if (res.ok) {
        addToast('Skill rejected');
        setProposals(prev => prev.filter(p => p.tool_id !== toolId));
      } else {
        addToast('Reject failed');
      }
    } catch (e) {
      addToast(e.message || 'Reject failed');
    } finally {
      setProposalActionBusy('');
    }
  };

  // ── Marketplace catalog (skills / daemons / mcp) ───────────────────────
  const fetchCatalog = async (kind) => {
    setCatalogLoading(prev => ({ ...prev, [kind]: true }));
    setCatalogError(prev => ({ ...prev, [kind]: false }));
    try {
      const res = await fetch(`${API}/api/marketplace/catalog?kind=${kind}`);
      if (!res.ok) {
        setCatalogError(prev => ({ ...prev, [kind]: true }));
        setCatalogItems(prev => ({ ...prev, [kind]: [] }));
        return;
      }
      const data = await res.json();
      setCatalogItems(prev => ({ ...prev, [kind]: data.items || data.results || [] }));
    } catch {
      setCatalogError(prev => ({ ...prev, [kind]: true }));
      setCatalogItems(prev => ({ ...prev, [kind]: [] }));
    } finally {
      setCatalogLoading(prev => ({ ...prev, [kind]: false }));
    }
  };

  const installCatalogItem = async (kind, id) => {
    const tag = `${kind}:${id}`;
    setInstallingItem(tag);
    try {
      const res = await fetch(`${API}/api/marketplace/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, id }),
      });
      if (res.ok) {
        addToast(`${kind === 'skill' ? 'Skill' : kind === 'daemon' ? 'Daemon' : 'MCP server'} installed`);
        if (kind === 'skill') fetchInstalledSkills();
      } else {
        addToast('Install failed — marketplace may be unavailable');
        setCatalogError(prev => ({ ...prev, [kind]: true }));
      }
    } catch (e) {
      addToast(e.message || 'Install failed');
    } finally {
      setInstallingItem('');
    }
  };

  const copyWebhookUrl = (url) => {
    const fullUrl = `${window.location.protocol}//${window.location.hostname}:9090${url}`;
    navigator.clipboard.writeText(fullUrl).then(() => {
      setCopiedUrl(url);
      setTimeout(() => setCopiedUrl(''), 2000);
    });
  };

  const fetchSpecialists = async () => {
    setSpecialistsLoading(true);
    try {
      const [listRes, proposalRes] = await Promise.all([
        fetch(`${API}/api/agents/list`).then(r => r.json()),
        fetch(`${API}/api/agents/proposals`).then(r => r.json()),
      ]);
      setSpecialists(listRes.agents || []);
      setSpawnProposals(proposalRes.proposals || []);
    } catch { /* agents may not be initialised */ }
    finally { setSpecialistsLoading(false); }
  };

  const spawnAgent = async (patternId) => {
    setSpawningId(patternId);
    try {
      await fetch(`${API}/api/agents/spawn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern_id: patternId }),
      });
      await fetchSpecialists();
      flash();
    } catch (e) { addToast(e.message || 'Spawn failed'); }
    finally { setSpawningId(''); }
  };

  const sendFeedback = async (agentId, positive) => {
    setFeedbackBusy(`${agentId}:${positive}`);
    try {
      await fetch(`${API}/api/agents/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, positive }),
      });
      await fetchSpecialists();
    } catch (e) { addToast(e.message || 'Feedback failed'); }
    finally { setFeedbackBusy(''); }
  };

  const fetchInstalledSkills = async () => {
    try {
      const data = await fetch(`${API}/api/marketplace/installed`).then(r => r.json());
      setInstalledSkills(data.skills || []);
    } catch { /* marketplace may not be initialised */ }
  };

  const searchMarketplace = async (q) => {
    setMarketplaceLoading(true);
    try {
      const data = await fetch(`${API}/api/marketplace/search?q=${encodeURIComponent(q)}`).then(r => r.json());
      setMarketplaceResults(data.results || []);
    } catch { setMarketplaceResults([]); }
    finally { setMarketplaceLoading(false); }
  };

  const installSkill = async (skillId) => {
    setInstallingSkill(skillId);
    try {
      await fetch(`${API}/api/marketplace/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId }),
      });
      await fetchInstalledSkills();
      flash();
    } catch (e) { addToast(e.message || 'Install failed'); }
    finally { setInstallingSkill(''); }
  };

  const fetchRoutines = () => {
    setRoutinesLoading(true);
    fetch(`${API}/api/routines`).then(r => r.json()).then(d => setRoutines(d.routines || []))
      .catch(e => addToast(e.message || 'Failed to load routines')).finally(() => setRoutinesLoading(false));
  };

  useEffect(() => {
    fetch(`${API}/api/config`).then(r => r.json()).then(cfg => {
      setConfig(cfg);
      if (cfg.channels) {
        setChannelsConfig(prev => ({
          telegram: { ...prev.telegram, ...(cfg.channels.telegram || {}) },
          discord: { ...prev.discord, ...(cfg.channels.discord || {}) },
          slack: { ...prev.slack, ...(cfg.channels.slack || {}) },
          whatsapp: { ...prev.whatsapp, ...(cfg.channels.whatsapp || {}) },
        }));
      }
    }).catch(e => addToast(e.message || 'Failed to load config'));
    fetch(`${API}/api/identity`).then(r => r.json()).then(setIdentity).catch(e => addToast(e.message || 'Failed to load identity'));
    fetch(`${API}/api/devices`).then(r => r.json()).then(d => setDevices(d.devices || [])).catch(e => addToast(e.message || 'Failed to load devices'));
    fetch(`${API}/api/llm/presets`).then(r => r.json()).then(d => setLlmPresets(d.presets || [])).catch(e => addToast(e.message || 'Failed to load presets'));
    fetch(`${API}/api/channels`).then(r => r.json()).then(d => setChannelStatus(d)).catch(e => addToast(e.message || 'Failed to load channels'));
    fetchPendingSkills();
    fetchRoutines();
    fetchInstalledSkills();
    fetchSpecialists();
    fetchWebhooks();
    fetchProposals();
    const proposalPollId = setInterval(fetchProposals, 5000);
    return () => clearInterval(proposalPollId);
  }, []);

  useEffect(() => {
    if (activeTab !== 'marketplace') return;
    const kindMap = { skills: 'skill', daemons: 'daemon', mcp: 'mcp' };
    const kind = kindMap[marketplaceSubtab] || 'skill';
    fetchCatalog(kind);
  }, [activeTab, marketplaceSubtab]);

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
    try {
      await fetch(`${API}/api/identity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(identity),
      });
      flash();
    } catch (e) { addToast(e.message || 'Failed to save identity'); }
    finally { setSaving(false); }
  };

  const saveSkillKey = async () => {
    if (!newSkillKey.id || !newSkillKey.key) return;
    try {
      await fetch(`${API}/api/config/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_keys: { [newSkillKey.id]: newSkillKey.key } }),
      });
      setNewSkillKey({ id: '', key: '' });
      const resp = await fetch(`${API}/api/config`);
      setConfig(await resp.json());
      flash();
    } catch (e) { addToast(e.message || 'Failed to save API key'); }
  };

  const flash = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const isPresetActive = (preset) => {
    if (!config?.llm) return false;
    return config.llm.provider === preset.provider && config.llm.model === preset.model;
  };

  const applyPreset = async (presetId) => {
    setApplyingPreset(presetId);
    setPresetFeedback('');
    try {
      const res = await fetch(`${API}/api/llm/presets/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset: presetId }),
      });
      const data = await res.json();
      if (!data.ok) {
        setPresetFeedback(data.error || 'Preset apply failed');
      } else {
        const cfg = await fetch(`${API}/api/config`).then(r => r.json());
        setConfig(cfg);
        setPresetFeedback(`Applied preset: ${presetId}`);
      }
    } catch (e) {
      setPresetFeedback(e.message || 'Preset apply failed');
    } finally {
      setApplyingPreset('');
    }
  };

  const fetchPendingSkills = async () => {
    setPendingLoading(true);
    try {
      const data = await fetch(`${API}/api/skills/pending`).then(r => r.json());
      setPendingSkills(data.pending || []);
    } catch {
      setPendingSkills([]);
    } finally {
      setPendingLoading(false);
    }
  };

  const decidePendingSkill = async (skillId, action) => {
    setPendingActionBusy(`${action}:${skillId}`);
    try {
      const endpoint = action === 'approve' ? 'approve' : 'reject';
      const data = await fetch(`${API}/api/skills/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId }),
      }).then(r => r.json());
      if (data.ok) {
        setPendingSkills(prev => prev.filter(s => s.skill_id !== skillId));
      }
    } finally {
      setPendingActionBusy('');
    }
  };

  if (!config) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 border-2 border-feral-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const tabs = [
    { id: 'identity', label: 'Identity', icon: User },
    { id: 'devices', label: 'Devices', icon: Bluetooth },
    { id: 'llm', label: 'AI Model', icon: Sparkles },
    { id: 'features', label: 'Features', icon: Zap },
    { id: 'channels', label: 'Channels', icon: MessageSquare },
    { id: 'routines', label: 'Routines', icon: Clock },
    { id: 'webhooks', label: 'Webhooks', icon: Webhook },
    { id: 'specialists', label: 'Specialists', icon: Users },
    { id: 'marketplace', label: 'Marketplace', icon: ShoppingBag },
    { id: 'proposals', label: 'Proposals', icon: AlertCircle },
    { id: 'keys', label: 'API Keys', icon: Key },
    { id: 'security', label: 'Security', icon: Shield },
    { id: 'server', label: 'Server', icon: Server },
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-4 lg:p-8 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl lg:text-2xl font-bold">Settings</h1>
            <p className="text-xs lg:text-sm text-feral-text-secondary mt-1">Configure FERAL to your needs</p>
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
                    ? 'bg-feral-accent/15 text-feral-accent border border-feral-accent/20'
                    : 'text-feral-text-muted hover:text-feral-text hover:bg-feral-card-hover border border-transparent'
                }`}
              >
                <Icon size={14} />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Proposed Skills (Tool Genesis) — always visible above tab content when there are proposals */}
        {proposals.length > 0 && (
          <Section title="Proposed Skills" icon={Sparkles}>
            <p className="text-xs text-feral-text-muted mb-4">
              FERAL's Tool Genesis has drafted new skills from detected patterns. Review, then approve to load or reject to discard.
            </p>
            <div className="space-y-3">
              {proposals.map((p) => {
                const approving = proposalActionBusy === `approve:${p.tool_id}`;
                const rejecting = proposalActionBusy === `reject:${p.tool_id}`;
                const chain = Array.isArray(p.source_sequence) ? p.source_sequence : [];
                const preview = (p.preview || '').slice(0, 400);
                return (
                  <div key={p.tool_id} className="bg-feral-bg/30 rounded-lg border border-feral-border p-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold truncate">{p.name || p.tool_id}</div>
                        <div className="text-[11px] text-feral-text-muted font-mono truncate">{p.tool_id}</div>
                        {p.description && (
                          <div className="text-xs text-feral-text-secondary mt-1">{p.description}</div>
                        )}
                      </div>
                      <div className="flex gap-2 flex-shrink-0">
                        <button
                          onClick={() => approveProposal(p.tool_id)}
                          disabled={proposalActionBusy !== ''}
                          className="px-3 py-1.5 text-xs rounded-lg bg-green-500/20 border border-green-500/30 text-green-300 hover:bg-green-500/30 transition disabled:opacity-50 flex items-center gap-1.5"
                        >
                          {approving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                          Approve
                        </button>
                        <button
                          onClick={() => rejectProposal(p.tool_id)}
                          disabled={proposalActionBusy !== ''}
                          className="px-3 py-1.5 text-xs rounded-lg bg-red-500/20 border border-red-500/30 text-red-300 hover:bg-red-500/30 transition disabled:opacity-50 flex items-center gap-1.5"
                        >
                          {rejecting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                          Reject
                        </button>
                      </div>
                    </div>
                    {chain.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1 text-[11px]">
                        <span className="text-feral-text-muted mr-1">Source:</span>
                        {chain.map((step, idx) => (
                          <React.Fragment key={`${p.tool_id}-step-${idx}`}>
                            <span className="bg-feral-bg/50 text-feral-text-secondary px-2 py-0.5 rounded-full font-mono">
                              {typeof step === 'string' ? step : (step.name || step.id || JSON.stringify(step))}
                            </span>
                            {idx < chain.length - 1 && (
                              <span className="text-feral-text-muted">→</span>
                            )}
                          </React.Fragment>
                        ))}
                      </div>
                    )}
                    {preview && (
                      <pre className="bg-feral-bg/60 border border-feral-border rounded-lg p-3 text-[11px] font-mono text-feral-text-secondary overflow-auto max-h-48 whitespace-pre">
{preview}
                      </pre>
                    )}
                    {p.created_at && (
                      <div className="text-[10px] text-feral-text-muted">
                        Created: {(() => {
                          const ts = typeof p.created_at === 'number' ? p.created_at : Date.parse(p.created_at) / 1000;
                          return Number.isFinite(ts) ? new Date(ts * 1000).toLocaleString() : String(p.created_at);
                        })()}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* Identity Tab */}
        {activeTab === 'identity' && identity && (
          <div className="space-y-5">
            <Section title="Agent Identity" icon={User}>
              <p className="text-xs text-feral-text-muted mb-4">
                Define who FERAL is. This shapes how it talks, thinks, and behaves.
                Stored at <code className="bg-feral-bg px-1.5 py-0.5 rounded font-mono text-[10px]">~/.feral/identity.yaml</code>
              </p>

              <div className="space-y-4">
                <div>
                  <label className="text-xs text-feral-text-secondary mb-1 block">Agent Name</label>
                  <input
                    className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent"
                    value={identity.name || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, name: e.target.value }))}
                    placeholder="FERAL"
                  />
                </div>

                <div>
                  <label className="text-xs text-feral-text-secondary mb-1 block">Tagline</label>
                  <input
                    className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent"
                    value={identity.tagline || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, tagline: e.target.value }))}
                    placeholder="Your personal AI operating system"
                  />
                </div>

                <div>
                  <label className="text-xs text-feral-text-secondary mb-1 block">Personality</label>
                  <textarea
                    rows={5}
                    className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent resize-none"
                    value={identity.personality || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, personality: e.target.value }))}
                    placeholder="Describe how FERAL should behave and communicate..."
                  />
                </div>

                <div>
                  <label className="text-xs text-feral-text-secondary mb-1 block">Rules (one per line)</label>
                  <textarea
                    rows={4}
                    className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent resize-none font-mono"
                    value={(identity.rules || []).join('\n')}
                    onChange={e => setIdentity(prev => ({ ...prev, rules: e.target.value.split('\n').filter(r => r.trim()) }))}
                    placeholder="Never make up sensor data&#10;Keep responses concise&#10;Always include units for health data"
                  />
                </div>

                <div>
                  <label className="text-xs text-feral-text-secondary mb-1 block">Communication Style</label>
                  <textarea
                    rows={3}
                    className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent resize-none"
                    value={identity.greeting_style || ''}
                    onChange={e => setIdentity(prev => ({ ...prev, greeting_style: e.target.value }))}
                    placeholder="How should FERAL greet and communicate..."
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-feral-text-secondary mb-1 block">TTS Voice</label>
                    <select
                      className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent"
                      value={identity.voice?.tts_voice || 'nova'}
                      onChange={e => setIdentity(prev => ({ ...prev, voice: { ...(prev.voice || {}), tts_voice: e.target.value } }))}
                    >
                      {['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'].map(v => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-feral-text-secondary mb-1 block">Style</label>
                    <select
                      className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent"
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
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-feral-accent text-white rounded-lg font-medium hover:bg-feral-accent/90 transition active:scale-[0.98] disabled:opacity-50"
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
              <p className="text-xs text-feral-text-muted mb-4">
                Hardware nodes connected to the FERAL Brain via WebSocket.
                Any device running a FERAL daemon can connect — phones, glasses, wristbands, robots.
              </p>

              {devices.length === 0 ? (
                <div className="text-center py-8 bg-feral-bg/30 rounded-xl border border-dashed border-feral-border">
                  <Radio size={32} className="mx-auto opacity-20 mb-3" />
                  <p className="text-sm text-feral-text-secondary">No devices connected</p>
                  <p className="text-xs text-feral-text-muted mt-2 max-w-xs mx-auto">
                    Devices connect automatically when they run a FERAL daemon.
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

            <PhoneBridgeSection />

            <Section title="How to Connect Devices" icon={Wifi}>
              <div className="space-y-3 text-sm">
                {[
                  { icon: Smartphone, name: 'Phone (iOS/Android)', desc: 'Install the FERAL Node app and scan the QR code above to pair your phone as a bridge for BLE devices.' },
                  { icon: Glasses, name: 'Smart Glasses', desc: 'Any BLE-capable glasses can connect through the phone bridge or a direct daemon. The glasses stream camera frames and mic audio.' },
                  { icon: Watch, name: 'Wristband / Watch', desc: 'Health sensors (HR, SpO2, temp) connect via BLE through a phone bridge or dedicated USB dongle daemon.' },
                  { icon: Bot, name: 'Robot / Custom Hardware', desc: 'Any device running Python or Kotlin can use the node SDK. Connect to ws://BRAIN_IP:9090/v1/node with your API key.' },
                ].map(item => (
                  <div key={item.name} className="flex gap-3 bg-feral-bg/30 rounded-lg p-3 border border-feral-border">
                    <item.icon size={20} className="text-feral-accent flex-shrink-0 mt-0.5" />
                    <div>
                      <div className="font-medium text-sm">{item.name}</div>
                      <div className="text-xs text-feral-text-secondary mt-0.5">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-4 bg-feral-bg border border-feral-border rounded-lg p-3">
                <label className="text-xs text-feral-text-secondary mb-1 block">Brain Address (for devices to connect)</label>
                <code className="text-sm text-feral-accent font-mono">
                  ws://{window.location.hostname}:9090/v1/node?api_key=<em>{'<NODE_API_KEY>'}</em>
                </code>
              </div>
            </Section>
          </div>
        )}

        {/* LLM Tab */}
        {activeTab === 'llm' && (
          <Section title="LLM Provider" icon={Sparkles}>
            <div className="space-y-4">
              {llmPresets.length > 0 && (
                <div>
                  <label className="text-xs text-feral-text-secondary mb-2 block">Provider Presets</label>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {llmPresets.map(preset => {
                      const active = isPresetActive(preset);
                      const applying = applyingPreset === preset.id;
                      return (
                        <button
                          key={preset.id}
                          onClick={() => applyPreset(preset.id)}
                          disabled={applyingPreset !== '' && !applying}
                          className={`text-left px-3 py-2 rounded-lg border transition ${
                            active
                              ? 'border-feral-accent bg-feral-accent/10'
                              : 'border-feral-border bg-feral-bg hover:border-feral-border-bright'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium">{preset.id}</span>
                            {active && <Check size={14} className="text-feral-accent" />}
                            {applying && <Loader2 size={14} className="animate-spin" />}
                          </div>
                          <div className="text-[11px] text-feral-text-secondary mt-1">{preset.description}</div>
                          <div className="text-[10px] text-feral-text-muted mt-1 font-mono">
                            {preset.provider}/{preset.model}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                  {presetFeedback && (
                    <div className="text-xs mt-2 text-feral-text-secondary">{presetFeedback}</div>
                  )}
                </div>
              )}

              <div className="grid grid-cols-4 gap-3">
                {[
                  { id: 'openai', label: 'OpenAI' },
                  { id: 'anthropic', label: 'Anthropic' },
                  { id: 'gemini', label: 'Gemini' },
                  { id: 'openrouter', label: 'OpenRouter' },
                  { id: 'deepseek', label: 'DeepSeek' },
                  { id: 'qwen', label: 'Qwen' },
                  { id: 'groq', label: 'Groq' },
                  { id: 'ollama', label: 'Ollama' },
                ].map(p => (
                  <button
                    key={p.id}
                    onClick={() => updateSetting('llm', 'provider', p.id)}
                    className={`px-4 py-3 rounded-lg border text-sm font-medium transition ${
                      config.llm?.provider === p.id
                        ? 'border-feral-accent bg-feral-accent/10 text-feral-accent'
                        : 'border-feral-border bg-feral-card hover:border-feral-border-bright'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <div>
                <label className="text-xs text-feral-text-secondary mb-1 block">Model</label>
                <input
                  className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent font-mono"
                  value={config.llm?.model || ''}
                  onChange={e => updateSetting('llm', 'model', e.target.value)}
                />
                {config.llm?.provider === 'ollama' && !/llava|moondream|qwen2-vl|minicpm-v|bakllava|gemma3/i.test(config.llm?.model || '') && (
                  <p className="text-[11px] text-yellow-400 mt-1">
                    This model may be text-only. For local vision, use preset <code>ollama_vision</code>.
                  </p>
                )}
              </div>
              <div>
                <label className="text-xs text-feral-text-secondary mb-1 block">Base URL (leave blank for defaults)</label>
                <input
                  className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent font-mono"
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
            <Section title="Appearance" icon={theme === 'dark' ? Moon : Sun}>
              <div className="flex items-center justify-between py-1">
                <div>
                  <div className="text-sm font-medium">Theme</div>
                  <div className="text-xs text-feral-text-secondary mt-0.5">Switch between light and dark mode</div>
                </div>
                <button
                  onClick={toggleTheme}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition ${
                    theme === 'dark'
                      ? 'border-feral-border bg-feral-card text-feral-text hover:border-feral-border-bright'
                      : 'border-feral-accent/30 bg-feral-accent/10 text-feral-accent'
                  }`}
                >
                  {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
                  {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
                </button>
              </div>
            </Section>

            <Section title="Features" icon={Zap}>
              <div className="space-y-3">
                <Toggle label="Streaming Responses" desc="Token-by-token LLM output in real-time" value={config.features?.streaming} onChange={v => updateSetting('features', 'streaming', v)} />
                <Toggle label="Proactive Agent" desc="Autonomous health and device alerts" value={config.features?.proactive} onChange={v => updateSetting('features', 'proactive', v)} />
                <Toggle label="Self-Learning" desc="Extract knowledge from conversations" value={config.features?.self_learning ?? true} onChange={v => updateSetting('features', 'self_learning', v)} />
                <Toggle label="Multi-Agent Mode" desc="Enable worker routing and subagent collaboration by default" value={config.features?.multi_agent ?? true} onChange={v => updateSetting('features', 'multi_agent', v)} />
              </div>
            </Section>

            <Section title="Autonomy Mode" icon={Shield}>
              <p className="text-xs text-feral-text-muted mb-3">
                Control how much freedom FERAL has to act on your behalf.
              </p>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: 'strict', label: 'Strict', desc: 'Every action requires your approval' },
                  { id: 'hybrid', label: 'Hybrid', desc: 'Safe actions auto-execute, risky ones ask first' },
                  { id: 'loose', label: 'Loose', desc: 'Full autonomy — only blocked actions need approval' },
                ].map(mode => (
                  <button
                    key={mode.id}
                    onClick={async () => {
                      try {
                        setConfig(prev => ({ ...prev, autonomy_mode: mode.id }));
                        await fetch(`${API}/api/config/update`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ section: 'security', key: 'autonomy_mode', value: mode.id }),
                        });
                        flash();
                      } catch (e) { addToast(e.message || 'Failed to update autonomy mode'); }
                    }}
                    className={`text-left px-4 py-3 rounded-lg border transition ${
                      (config.autonomy_mode || 'hybrid') === mode.id
                        ? 'border-feral-accent bg-feral-accent/10 text-feral-accent'
                        : 'border-feral-border bg-feral-card hover:border-feral-border-bright'
                    }`}
                  >
                    <div className="text-sm font-medium">{mode.label}</div>
                    <div className="text-[11px] text-feral-text-secondary mt-1">{mode.desc}</div>
                  </button>
                ))}
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
                  <label className="text-xs text-feral-text-secondary mb-1 block">TTS Voice</label>
                  <select
                    className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent"
                    value={config.audio?.tts_voice || 'nova'}
                    onChange={e => updateSetting('audio', 'tts_voice', e.target.value)}
                  >
                    {['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'].map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-feral-text-secondary mb-1 block">STT Model</label>
                  <input
                    className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent font-mono"
                    value={config.audio?.stt_model || 'whisper-1'}
                    onChange={e => updateSetting('audio', 'stt_model', e.target.value)}
                  />
                </div>
              </div>
            </Section>

            <Section title="Voice Provider" icon={Volume2}>
              <p className="text-xs text-feral-text-muted mb-3">
                Choose which realtime voice backend powers voice conversations.
              </p>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: 'openai', label: 'OpenAI Realtime', desc: 'GPT-4o realtime voice API' },
                  { id: 'gemini', label: 'Gemini Live', desc: 'Google Gemini multimodal live' },
                  { id: 'local', label: 'Local (Whisper + Piper)', desc: 'On-device STT/TTS — no API key needed' },
                ].map(vp => (
                  <button
                    key={vp.id}
                    onClick={async () => {
                      try {
                        setConfig(prev => ({ ...prev, voice_provider: vp.id }));
                        await fetch(`${API}/api/config/update`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ section: 'audio', key: 'voice_provider', value: vp.id }),
                        });
                        flash();
                      } catch (e) { addToast(e.message || 'Failed to update voice provider'); }
                    }}
                    className={`text-left px-4 py-3 rounded-lg border transition ${
                      (config.voice_provider || 'openai') === vp.id
                        ? 'border-feral-accent bg-feral-accent/10 text-feral-accent'
                        : 'border-feral-border bg-feral-card hover:border-feral-border-bright'
                    }`}
                  >
                    <div className="text-sm font-medium">{vp.label}</div>
                    <div className="text-[11px] text-feral-text-secondary mt-1">{vp.desc}</div>
                  </button>
                ))}
              </div>
            </Section>

            <Section title="Voice Input Mode" icon={Volume2}>
              <p className="text-xs text-feral-text-muted mb-3">
                Choose how the microphone is activated during voice sessions.
              </p>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { id: 'toggle', label: 'Toggle Voice', desc: 'Click to start/stop — always-on mic during voice session' },
                  { id: 'push_to_talk', label: 'Push-to-Talk', desc: 'Hold Space to speak, release to send' },
                ].map(m => (
                  <button
                    key={m.id}
                    onClick={async () => {
                      try {
                        setConfig(prev => ({ ...prev, voice_input_mode: m.id }));
                        await fetch(`${API}/api/config/update`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ section: 'audio', key: 'voice_input_mode', value: m.id }),
                        });
                        flash();
                      } catch (e) { addToast(e.message || 'Failed to update voice input mode'); }
                    }}
                    className={`text-left px-4 py-3 rounded-lg border transition ${
                      (config.voice_input_mode || 'toggle') === m.id
                        ? 'border-feral-accent bg-feral-accent/10 text-feral-accent'
                        : 'border-feral-border bg-feral-card hover:border-feral-border-bright'
                    }`}
                  >
                    <div className="text-sm font-medium">{m.label}</div>
                    <div className="text-[11px] text-feral-text-secondary mt-1">{m.desc}</div>
                  </button>
                ))}
              </div>
            </Section>
          </div>
        )}

        {/* Channels Tab */}
        {activeTab === 'channels' && (
          <Section title="Messaging Channels" icon={MessageSquare}>
            <p className="text-xs text-feral-text-muted mb-4">
              Connect FERAL to messaging platforms. Enable channels to interact with your agent from anywhere.
            </p>
            <div className="space-y-4">
              {[
                { id: 'telegram', label: 'Telegram', fields: [{ key: 'bot_token', label: 'Bot Token', secret: true }] },
                { id: 'discord', label: 'Discord', fields: [{ key: 'bot_token', label: 'Bot Token', secret: true }] },
                { id: 'slack', label: 'Slack', fields: [{ key: 'bot_token', label: 'Bot Token', secret: true }, { key: 'app_token', label: 'App Token', secret: true }] },
                { id: 'whatsapp', label: 'WhatsApp', fields: [{ key: 'access_token', label: 'Access Token', secret: true }, { key: 'phone_number_id', label: 'Phone Number ID', secret: false }] },
              ].map(ch => {
                const chCfg = channelsConfig[ch.id] || {};
                const status =
                  channelStatus?.[ch.id] ||
                  channelStatus?.details?.[ch.id] ||
                  channelStatus?.channels?.[ch.id];
                const isRunning = Boolean(status?.running);
                const isConnected = Boolean(status?.connected) || status?.status === 'connected' || isRunning;
                // If the brain is actually running the channel, the toggle should reflect that
                // even when the user never clicked the switch (fresh wizard install path).
                const toggleOn = Boolean(chCfg.enabled) || isRunning;
                const statusLabel = isConnected
                  ? (status?.bot_username ? `Connected as @${status.bot_username}` : 'Connected')
                  : (isRunning ? 'Starting…' : 'Disconnected');
                return (
                  <div key={ch.id} className="bg-feral-bg/30 rounded-lg border border-feral-border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${isConnected ? 'bg-green-400' : (isRunning ? 'bg-yellow-400' : 'bg-zinc-500')}`} />
                        <span className="text-sm font-medium">{ch.label}</span>
                        <span className="text-[10px] text-feral-text-muted">{statusLabel}</span>
                      </div>
                      <button
                        onClick={() => setChannelsConfig(prev => ({
                          ...prev,
                          [ch.id]: { ...prev[ch.id], enabled: !toggleOn },
                        }))}
                        className={`w-12 h-7 rounded-full transition-all flex items-center px-1 ${
                          toggleOn ? 'bg-feral-accent justify-end' : 'bg-zinc-700 justify-start'
                        }`}
                      >
                        <div className="w-5 h-5 bg-white rounded-full shadow transition-all" />
                      </button>
                    </div>
                    {toggleOn && (
                      <div className="space-y-2 pt-1">
                        {ch.fields.map(f => (
                          <div key={f.key}>
                            <label className="text-xs text-feral-text-secondary mb-1 block">{f.label}</label>
                            <input
                              type={f.secret ? 'password' : 'text'}
                              className="w-full bg-feral-bg border border-feral-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent font-mono"
                              value={chCfg[f.key] || ''}
                              onChange={e => setChannelsConfig(prev => ({
                                ...prev,
                                [ch.id]: { ...prev[ch.id], [f.key]: e.target.value },
                              }))}
                              placeholder={`Enter ${f.label.toLowerCase()}`}
                            />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              <button
                onClick={async () => {
                  setChannelsSaving(true);
                  try {
                    await fetch(`${API}/api/config/update`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ section: 'channels', key: 'channels', value: channelsConfig }),
                    });
                    const st = await fetch(`${API}/api/channels`).then(r => r.json());
                    setChannelStatus(st);
                    flash();
                  } catch (e) {
                    addToast(e.message || 'Failed to save channels');
                  } finally {
                    setChannelsSaving(false);
                  }
                }}
                disabled={channelsSaving}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-feral-accent text-white rounded-lg font-medium hover:bg-feral-accent/90 transition active:scale-[0.98] disabled:opacity-50"
              >
                {channelsSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                Save Channels
              </button>
            </div>
          </Section>
        )}

        {/* Routines Tab */}
        {activeTab === 'routines' && (
          <Section title="Routines" icon={Clock}>
            <div className="space-y-4">
              <p className="text-xs text-feral-text-muted">
                Automated tasks that run on a schedule, trigger, or chain. Create routines to let FERAL work in the background.
              </p>

              {/* Create routine */}
              <div className="bg-feral-card border border-feral-border rounded-lg p-3 space-y-2">
                <div className="text-xs font-medium text-feral-text-secondary">New Routine</div>
                <input
                  className="w-full bg-feral-bg border border-feral-border rounded px-2.5 py-1.5 text-xs text-feral-text placeholder-feral-text-muted"
                  placeholder="Description (e.g. Check weather every morning)"
                  value={newRoutine.description}
                  onChange={e => setNewRoutine(p => ({ ...p, description: e.target.value }))}
                />
                <div className="flex gap-2">
                  <input
                    className="flex-1 bg-feral-bg border border-feral-border rounded px-2.5 py-1.5 text-xs text-feral-text placeholder-feral-text-muted font-mono"
                    placeholder="Schedule (every 60m, daily 08:00)"
                    value={newRoutine.cron_expr}
                    onChange={e => setNewRoutine(p => ({ ...p, cron_expr: e.target.value }))}
                  />
                </div>
                <input
                  className="w-full bg-feral-bg border border-feral-border rounded px-2.5 py-1.5 text-xs text-feral-text placeholder-feral-text-muted"
                  placeholder="Prompt or action (e.g. Summarize my calendar for today)"
                  value={newRoutine.prompt}
                  onChange={e => setNewRoutine(p => ({ ...p, prompt: e.target.value }))}
                />
                <button
                  className="px-3 py-1.5 text-xs font-medium rounded bg-feral-accent/15 border border-feral-accent/25 text-feral-accent hover:bg-feral-accent/25 transition"
                  onClick={async () => {
                    if (!newRoutine.description) return;
                    await fetch(`${API}/api/routines`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        job_type: 'scheduled',
                        cron_expr: newRoutine.cron_expr || 'every 60m',
                        description: newRoutine.description,
                        payload: { prompt: newRoutine.prompt },
                        prompt: newRoutine.prompt,
                      }),
                    });
                    setNewRoutine({ description: '', cron_expr: 'every 60m', prompt: '' });
                    fetchRoutines();
                  }}
                >
                  <Plus size={11} className="inline mr-1" />
                  Create Routine
                </button>
              </div>

              {/* Routines list */}
              {routinesLoading && <Loader2 size={16} className="animate-spin text-feral-text-muted" />}
              {!routinesLoading && routines.length === 0 && (
                <div className="text-xs text-feral-text-muted text-center py-4">No routines yet.</div>
              )}
              {routines.map(r => {
                const isExpanded = expandedRoutine === r.id;
                const runs = routineRuns[r.id] || [];
                return (
                  <div key={r.id} className="bg-feral-card border border-feral-border rounded-lg overflow-hidden">
                    <div className="flex items-center gap-2 px-3 py-2">
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${r.enabled ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
                      <span className="text-xs font-medium text-feral-text flex-1 truncate">{r.description || `Routine #${r.id}`}</span>
                      <span className="text-[10px] text-feral-text-muted font-mono flex-shrink-0">{r.cron_expr}</span>
                      <span className="text-[10px] text-feral-text-muted flex-shrink-0">{r.run_count} runs</span>
                      <button
                        className="p-1 text-feral-text-muted hover:text-feral-text transition"
                        title={r.enabled ? 'Pause' : 'Resume'}
                        onClick={async () => {
                          const ep = r.enabled ? 'pause' : 'resume';
                          await fetch(`${API}/api/routines/${r.id}/${ep}`, { method: 'POST' });
                          fetchRoutines();
                        }}
                      >
                        {r.enabled ? <Pause size={12} /> : <Play size={12} />}
                      </button>
                      <button
                        className="p-1 text-feral-text-muted hover:text-rose-400 transition"
                        title="Delete"
                        onClick={async () => {
                          await fetch(`${API}/api/routines/${r.id}`, { method: 'DELETE' });
                          fetchRoutines();
                        }}
                      >
                        <Trash2 size={12} />
                      </button>
                      <button
                        className="p-1 text-feral-text-muted hover:text-feral-text transition"
                        onClick={async () => {
                          if (isExpanded) {
                            setExpandedRoutine(null);
                          } else {
                            setExpandedRoutine(r.id);
                            const res = await fetch(`${API}/api/routines/${r.id}/runs?limit=10`);
                            const data = await res.json();
                            setRoutineRuns(prev => ({ ...prev, [r.id]: data.runs || [] }));
                          }
                        }}
                      >
                        {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                      </button>
                    </div>
                    {isExpanded && (
                      <div className="border-t border-feral-border/50 px-3 py-2 space-y-1">
                        <div className="text-[10px] text-feral-text-muted">
                          Type: {r.job_type} | Created: {new Date(r.created_at * 1000).toLocaleString()}
                          {r.last_run && ` | Last: ${new Date(r.last_run * 1000).toLocaleString()}`}
                        </div>
                        {runs.length > 0 ? (
                          <div className="space-y-0.5 mt-1">
                            <div className="text-[10px] font-medium text-feral-text-secondary">Recent Runs</div>
                            {runs.map(run => (
                              <div key={run.id} className="flex items-center gap-2 text-[10px]">
                                <span className={`w-1 h-1 rounded-full ${run.status === 'success' ? 'bg-emerald-400' : run.status === 'error' ? 'bg-rose-400' : 'bg-amber-400'}`} />
                                <span className="text-feral-text-muted">{new Date(run.started_at * 1000).toLocaleString()}</span>
                                <span className={`${run.status === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>{run.status}</span>
                                {run.error && <span className="text-rose-400/70 truncate flex-1">{run.error}</span>}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-[10px] text-feral-text-muted">No runs yet.</div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* Webhooks Tab */}
        {activeTab === 'webhooks' && (
          <Section title="Webhook Management" icon={Webhook}>
            <div className="space-y-4">
              <p className="text-xs text-feral-text-muted">
                Create webhook endpoints that external services can POST to. Incoming events are routed to FERAL's orchestrator.
              </p>

              <div className="bg-feral-card border border-feral-border rounded-lg p-3 space-y-2">
                <div className="text-xs font-medium text-feral-text-secondary">Create Webhook</div>
                <input
                  className="w-full bg-feral-bg border border-feral-border rounded px-2.5 py-1.5 text-xs text-feral-text placeholder-feral-text-muted"
                  placeholder="Webhook name (e.g. GitHub Push)"
                  value={newWebhook.name}
                  onChange={e => setNewWebhook(p => ({ ...p, name: e.target.value }))}
                />
                <div className="flex gap-2">
                  <input
                    type="password"
                    className="flex-1 bg-feral-bg border border-feral-border rounded px-2.5 py-1.5 text-xs text-feral-text placeholder-feral-text-muted font-mono"
                    placeholder="Secret (optional, for HMAC verification)"
                    value={newWebhook.secret}
                    onChange={e => setNewWebhook(p => ({ ...p, secret: e.target.value }))}
                  />
                  <select
                    className="bg-feral-bg border border-feral-border rounded px-2.5 py-1.5 text-xs text-feral-text"
                    value={newWebhook.action}
                    onChange={e => setNewWebhook(p => ({ ...p, action: e.target.value }))}
                  >
                    <option value="chat">Chat</option>
                    <option value="skill">Skill</option>
                    <option value="routine">Routine</option>
                    <option value="intent">Intent</option>
                  </select>
                </div>
                <button
                  className="px-3 py-1.5 text-xs font-medium rounded bg-feral-accent/15 border border-feral-accent/25 text-feral-accent hover:bg-feral-accent/25 transition disabled:opacity-50"
                  onClick={createWebhook}
                  disabled={!newWebhook.name || creatingWebhook}
                >
                  {creatingWebhook ? <Loader2 size={11} className="inline mr-1 animate-spin" /> : <Plus size={11} className="inline mr-1" />}
                  Create Webhook
                </button>
              </div>

              {webhooksLoading && <Loader2 size={16} className="animate-spin text-feral-text-muted" />}
              {!webhooksLoading && webhooks.length === 0 && (
                <div className="text-center py-6 bg-feral-bg/30 rounded-xl border border-dashed border-feral-border">
                  <Link size={28} className="mx-auto opacity-20 mb-2" />
                  <p className="text-sm text-feral-text-secondary">No webhooks created</p>
                  <p className="text-xs text-feral-text-muted mt-1">Create one above to receive events from external services</p>
                </div>
              )}

              {webhooks.map(hook => (
                <div key={hook.id} className="bg-feral-bg/30 rounded-lg border border-feral-border p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Webhook size={14} className="text-feral-accent" />
                      <span className="text-sm font-medium">{hook.name}</span>
                      <span className="text-[10px] bg-feral-bg px-2 py-0.5 rounded-full text-feral-text-muted font-mono">{hook.action}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => copyWebhookUrl(hook.url)}
                        className="p-1.5 rounded-lg hover:bg-feral-accent/10 transition"
                        title="Copy URL"
                      >
                        {copiedUrl === hook.url ? <Check size={14} className="text-green-400" /> : <Copy size={14} className="text-feral-text-muted" />}
                      </button>
                      <button
                        onClick={() => deleteWebhook(hook.id)}
                        className="p-1.5 rounded-lg hover:bg-rose-500/10 transition"
                        title="Delete"
                      >
                        <Trash2 size={14} className="text-rose-400" />
                      </button>
                    </div>
                  </div>
                  <div className="text-[11px] text-feral-text-muted font-mono bg-feral-bg/50 rounded px-2.5 py-1.5 mb-2 break-all">
                    {window.location.protocol}//{window.location.hostname}:9090{hook.url}
                  </div>
                  <div className="flex items-center gap-4 text-[11px] text-feral-text-muted">
                    <span>Triggers: <strong className="text-feral-text-secondary">{hook.trigger_count}</strong></span>
                    <span>Last: <strong className="text-feral-text-secondary">{hook.last_triggered ? new Date(hook.last_triggered * 1000).toLocaleString() : 'Never'}</strong></span>
                    {hook.secret && <span className="text-green-400">HMAC verified</span>}
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Specialists Tab */}
        {activeTab === 'specialists' && (
          <div className="space-y-5">
            <Section title="Specialist Agents" icon={Users}>
              <p className="text-xs text-feral-text-muted mb-4">
                FERAL automatically detects recurring task patterns and can spawn persistent specialist agents.
              </p>

              {specialistsLoading && <Loader2 size={16} className="animate-spin text-feral-text-muted" />}

              {!specialistsLoading && specialists.length === 0 && spawnProposals.length === 0 && (
                <div className="text-center py-8 bg-feral-bg/30 rounded-xl border border-dashed border-feral-border">
                  <Bot size={32} className="mx-auto opacity-20 mb-3" />
                  <p className="text-sm text-feral-text-secondary">No specialists yet</p>
                  <p className="text-xs text-feral-text-muted mt-1">Keep using FERAL — recurring patterns will generate proposals</p>
                </div>
              )}

              {specialists.length > 0 && (
                <div className="space-y-3">
                  <div className="text-xs text-feral-text-secondary uppercase tracking-wider">Active Specialists</div>
                  {specialists.map(agent => (
                    <div key={agent.agent_id} className="bg-feral-bg/30 rounded-lg border border-feral-border p-4">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <Bot size={16} className="text-feral-accent" />
                          <span className="text-sm font-medium">{agent.name}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => sendFeedback(agent.agent_id, true)}
                            disabled={feedbackBusy !== ''}
                            className="p-1.5 rounded-lg hover:bg-emerald-500/10 transition disabled:opacity-50"
                            title="Good job"
                          >
                            <ThumbsUp size={14} className="text-emerald-400" />
                          </button>
                          <button
                            onClick={() => sendFeedback(agent.agent_id, false)}
                            disabled={feedbackBusy !== ''}
                            className="p-1.5 rounded-lg hover:bg-rose-500/10 transition disabled:opacity-50"
                            title="Needs improvement"
                          >
                            <ThumbsDown size={14} className="text-rose-400" />
                          </button>
                        </div>
                      </div>
                      <div className="text-xs text-feral-text-secondary mb-2">{agent.description}</div>
                      <div className="grid grid-cols-3 gap-2">
                        <div className="bg-feral-bg/40 rounded px-2 py-1.5">
                          <div className="text-[10px] text-feral-text-muted">Satisfaction</div>
                          <div className={`text-sm font-bold ${agent.satisfaction >= 0.7 ? 'text-emerald-400' : agent.satisfaction >= 0.4 ? 'text-amber-400' : 'text-rose-400'}`}>
                            {Math.round(agent.satisfaction * 100)}%
                          </div>
                        </div>
                        <div className="bg-feral-bg/40 rounded px-2 py-1.5">
                          <div className="text-[10px] text-feral-text-muted">Tasks</div>
                          <div className="text-sm font-bold text-feral-accent">{agent.tasks}</div>
                        </div>
                        <div className="bg-feral-bg/40 rounded px-2 py-1.5">
                          <div className="text-[10px] text-feral-text-muted">Tools</div>
                          <div className="text-sm font-bold text-feral-text-secondary">{(agent.tools || []).length}</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            {spawnProposals.length > 0 && (
              <Section title="Spawn Proposals" icon={Sparkles}>
                <p className="text-xs text-feral-text-muted mb-4">
                  These patterns have been detected frequently. Spawn them as persistent specialists.
                </p>
                <div className="space-y-3">
                  {spawnProposals.map(proposal => (
                    <div key={proposal.pattern_id} className="bg-feral-bg/30 rounded-lg border border-feral-border p-4">
                      <div className="flex items-center justify-between mb-2">
                        <div>
                          <div className="text-sm font-medium">{proposal.name}</div>
                          <div className="text-[11px] text-feral-text-muted">
                            {proposal.topic} · seen {proposal.seen_count}x
                            {proposal.time_pattern && ` · ${proposal.time_pattern}`}
                          </div>
                        </div>
                        <button
                          onClick={() => spawnAgent(proposal.pattern_id)}
                          disabled={spawningId !== ''}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-feral-accent/15 border border-feral-accent/25 text-feral-accent hover:bg-feral-accent/25 transition disabled:opacity-50"
                        >
                          {spawningId === proposal.pattern_id
                            ? <Loader2 size={12} className="animate-spin" />
                            : <Zap size={12} />}
                          Spawn
                        </button>
                      </div>
                      {proposal.tools && proposal.tools.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {proposal.tools.slice(0, 5).map(t => (
                            <span key={t} className="text-[10px] bg-feral-bg/50 text-feral-text-muted px-2 py-0.5 rounded-full font-mono">{t}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </div>
        )}

        {/* Marketplace Tab */}
        {activeTab === 'marketplace' && (
          <div className="space-y-5">
            <Section title="Marketplace" icon={ShoppingBag}>
              <p className="text-xs text-feral-text-muted mb-4">
                Browse and install skills, hardware daemons, and MCP servers from registry.feral.sh.
              </p>

              {/* Subtab buttons */}
              <div className="flex gap-1 mb-4 p-1 bg-feral-bg/40 border border-feral-border rounded-lg w-fit">
                {[
                  { id: 'skills', label: 'Skills', icon: Sparkles, kind: 'skill' },
                  { id: 'daemons', label: 'Hardware Daemons', icon: Cpu, kind: 'daemon' },
                  { id: 'mcp', label: 'MCP Servers', icon: Server, kind: 'mcp' },
                ].map(sub => {
                  const SIcon = sub.icon;
                  const active = marketplaceSubtab === sub.id;
                  return (
                    <button
                      key={sub.id}
                      onClick={() => setMarketplaceSubtab(sub.id)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                        active
                          ? 'bg-feral-accent/15 text-feral-accent border border-feral-accent/25'
                          : 'text-feral-text-muted hover:text-feral-text border border-transparent'
                      }`}
                    >
                      <SIcon size={12} />
                      {sub.label}
                    </button>
                  );
                })}
              </div>

              {(() => {
                const kindMap = { skills: 'skill', daemons: 'daemon', mcp: 'mcp' };
                const kind = kindMap[marketplaceSubtab] || 'skill';
                const items = catalogItems[kind] || [];
                const loading = catalogLoading[kind];
                const errored = catalogError[kind];
                const accentIcon = kind === 'daemon' ? Cpu : kind === 'mcp' ? Server : Sparkles;
                const AccentIcon = accentIcon;

                if (errored) {
                  return (
                    <div className="flex items-start gap-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
                      <AlertCircle size={16} className="text-yellow-400 flex-shrink-0 mt-0.5" />
                      <div className="text-xs text-yellow-100/90">
                        Marketplace unavailable — the registry.feral.sh service is being provisioned.
                      </div>
                    </div>
                  );
                }

                if (loading) {
                  return (
                    <div className="flex items-center gap-2 text-xs text-feral-text-muted py-4">
                      <Loader2 size={14} className="animate-spin" />
                      Loading catalog…
                    </div>
                  );
                }

                if (items.length === 0) {
                  return (
                    <div className="text-center py-6 bg-feral-bg/30 rounded-xl border border-dashed border-feral-border">
                      <AccentIcon size={28} className="mx-auto opacity-20 mb-2" />
                      <p className="text-sm text-feral-text-secondary">Nothing here yet</p>
                      <p className="text-xs text-feral-text-muted mt-1">Check back soon — the catalog is still filling up.</p>
                    </div>
                  );
                }

                return (
                  <div className="space-y-2">
                    {items.map(item => {
                      const id = item.id || item.skill_id || item.slug;
                      const tag = `${kind}:${id}`;
                      const busy = installingItem === tag;
                      const verified = Boolean(item.verified);
                      return (
                        <div key={id} className="flex items-start gap-3 bg-feral-bg/30 border border-feral-border rounded-lg px-4 py-3">
                          <div className="w-9 h-9 rounded-lg bg-feral-accent/10 flex items-center justify-center flex-shrink-0">
                            <AccentIcon size={16} className="text-feral-accent" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <div className="text-sm font-medium truncate">{item.name || id}</div>
                              <span className={`text-[10px] px-2 py-0.5 rounded-full flex-shrink-0 ${
                                verified
                                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                  : 'bg-feral-bg/60 text-feral-text-muted border border-feral-border'
                              }`}>
                                {verified ? 'verified' : 'community'}
                              </span>
                              {item.version && (
                                <span className="text-[10px] text-feral-text-muted font-mono">v{item.version}</span>
                              )}
                            </div>
                            {item.description && (
                              <div className="text-xs text-feral-text-secondary mt-0.5 truncate">{item.description}</div>
                            )}
                            {item.author && (
                              <div className="text-[10px] text-feral-text-muted mt-1">by {item.author}</div>
                            )}
                          </div>
                          <button
                            onClick={() => installCatalogItem(kind, id)}
                            disabled={installingItem !== ''}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-feral-accent/15 border border-feral-accent/25 text-feral-accent hover:bg-feral-accent/25 transition disabled:opacity-50 flex-shrink-0"
                          >
                            {busy ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                            Install
                          </button>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </Section>

            <Section title="Installed Marketplace Skills" icon={Download}>
              {installedSkills.length === 0 ? (
                <div className="text-sm text-feral-text-muted bg-feral-bg/30 rounded-lg px-4 py-4 border border-feral-border text-center">
                  No marketplace skills installed yet. Browse the catalog above to find and install skills.
                </div>
              ) : (
                <div className="space-y-2">
                  {installedSkills.map(skill => (
                    <div key={skill.skill_id || skill.id} className="flex items-center gap-3 bg-feral-bg/30 border border-feral-border rounded-lg px-4 py-3">
                      <div className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{skill.name || skill.skill_id || skill.id}</div>
                        <div className="text-[11px] text-feral-text-muted font-mono">{skill.version || 'latest'}</div>
                      </div>
                      <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full flex-shrink-0">Installed</span>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </div>
        )}

        {/* Proposals Tab */}
        {activeTab === 'proposals' && (
          <Section title="Generated Skill Proposals" icon={AlertCircle}>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-feral-text-muted">
                  Skills generated by the agent that are waiting for your approval.
                </p>
                <button
                  onClick={fetchPendingSkills}
                  className="text-xs px-2 py-1 rounded bg-feral-card border border-feral-border hover:border-feral-accent flex items-center gap-1"
                  disabled={pendingLoading}
                >
                  <RefreshCw size={12} className={pendingLoading ? 'animate-spin' : ''} />
                  Refresh
                </button>
              </div>

              {pendingSkills.length === 0 && !pendingLoading && (
                <div className="text-sm text-feral-text-muted bg-feral-bg/30 rounded-lg px-4 py-4 border border-feral-border">
                  No pending skill proposals.
                </div>
              )}

              {pendingSkills.map((skill) => (
                <div key={skill.skill_id} className="bg-feral-bg/30 rounded-lg border border-feral-border p-4 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold">{skill.brand?.name || skill.skill_id}</div>
                      <div className="text-[11px] text-feral-text-muted font-mono">{skill.skill_id}</div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => decidePendingSkill(skill.skill_id, 'approve')}
                        disabled={pendingActionBusy !== ''}
                        className="px-3 py-1.5 text-xs rounded-lg bg-green-500/20 border border-green-500/30 text-green-300 disabled:opacity-50"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => decidePendingSkill(skill.skill_id, 'reject')}
                        disabled={pendingActionBusy !== ''}
                        className="px-3 py-1.5 text-xs rounded-lg bg-red-500/20 border border-red-500/30 text-red-300 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                  <div className="text-xs text-feral-text-secondary">{skill.description || 'No description'}</div>
                  <div className="text-[11px] text-feral-text-muted">Endpoints: {skill.endpoints?.length || 0}</div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* API Keys Tab */}
        {activeTab === 'keys' && (
          <Section title="Skill API Keys" icon={Key}>
            <div className="space-y-3">
              {config.has_skill_keys?.map(id => (
                <div key={id} className="flex items-center justify-between bg-feral-bg/30 rounded-lg px-4 py-3">
                  <span className="text-sm font-mono">{id}</span>
                  <span className="text-xs text-green-400 flex items-center gap-1"><Check size={12} /> Configured</span>
                </div>
              ))}

              <div className="flex items-center gap-2 pt-2">
                <input
                  placeholder="skill_id"
                  className="flex-1 bg-feral-bg border border-feral-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent font-mono"
                  value={newSkillKey.id}
                  onChange={e => setNewSkillKey(prev => ({ ...prev, id: e.target.value }))}
                />
                <input
                  type="password"
                  placeholder="API key"
                  className="flex-1 bg-feral-bg border border-feral-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent font-mono"
                  value={newSkillKey.key}
                  onChange={e => setNewSkillKey(prev => ({ ...prev, key: e.target.value }))}
                />
                <button
                  onClick={saveSkillKey}
                  disabled={!newSkillKey.id || !newSkillKey.key}
                  className="px-4 py-2 bg-feral-accent text-white rounded-lg text-sm font-medium hover:bg-feral-accent/80 disabled:opacity-30 transition flex items-center gap-1.5 flex-shrink-0"
                >
                  <Plus size={14} />
                  Add
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
                <label className="text-xs text-feral-text-secondary mb-1 block">Node API Key</label>
                <input
                  type="password"
                  className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent font-mono"
                  value={config.security?.node_api_key || ''}
                  onChange={e => updateSetting('security', 'node_api_key', e.target.value)}
                />
                <p className="text-xs text-feral-text-muted mt-1">Used to authenticate hardware daemon connections</p>
              </div>
            </Section>

            <Section title="Memory" icon={Database}>
              <p className="text-sm text-feral-text-secondary">
                Memory data stored at <code className="text-xs bg-feral-bg px-2 py-1 rounded font-mono">~/.feral/memory.db</code>
              </p>
              <div className="flex gap-3 mt-3">
                <button
                  onClick={() => {
                    fetch(`${API}/api/memory/export`)
                      .then(r => r.blob())
                      .then(b => {
                        const a = document.createElement('a');
                        a.href = URL.createObjectURL(b);
                        a.download = 'feral-memory.json';
                        a.click();
                      })
                      .catch(e => addToast(e.message || 'Failed to export memory'));
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-feral-card border border-feral-border rounded-lg text-sm hover:bg-feral-card-hover transition"
                >
                  <Database size={14} /> Export
                </button>
                <button
                  onClick={() => {
                    if (window.confirm('Clear all memory? This cannot be undone.'))
                      fetch(`${API}/api/memory/clear`, { method: 'POST' })
                        .catch(e => addToast(e.message || 'Failed to clear memory'));
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-red-900/30 border border-red-800 rounded-lg text-sm text-red-400 hover:bg-red-900/50 transition"
                >
                  <Trash2 size={14} /> Clear All
                </button>
              </div>
            </Section>
          </div>
        )}

        {/* Server Tab */}
        {activeTab === 'server' && (
          <Section title="Server Configuration" icon={Server}>
            <p className="text-xs text-feral-text-muted mb-4">
              Read-only server settings. These values are derived from your environment and config files.
            </p>
            <div className="space-y-4">
              <div>
                <label className="text-xs text-feral-text-secondary mb-1 block">Bind Address</label>
                <div className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm font-mono text-feral-text-muted">
                  {config.server?.bind_address || config.bind_address || '127.0.0.1'}
                </div>
              </div>
              <div>
                <label className="text-xs text-feral-text-secondary mb-1 block">Brain Port</label>
                <div className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm font-mono text-feral-text-muted">
                  {config.server?.port || config.port || '9090'}
                </div>
              </div>
              <div>
                <label className="text-xs text-feral-text-secondary mb-1 block">CORS Origins</label>
                <div className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm font-mono text-feral-text-muted">
                  {config.server?.cors_origins || config.cors_origins || '*'}
                </div>
              </div>
              <div>
                <label className="text-xs text-feral-text-secondary mb-1 block">Node API Key</label>
                <input
                  type="password"
                  readOnly
                  className="w-full bg-feral-bg border border-feral-border rounded-lg px-4 py-2.5 text-sm font-mono text-feral-text-muted cursor-default"
                  value={config.security?.node_api_key || ''}
                  placeholder="Not configured"
                />
              </div>
            </div>
            <div className="mt-4 bg-feral-bg/50 border border-feral-border rounded-lg px-4 py-3">
              <p className="text-xs text-feral-text-secondary flex items-center gap-2">
                <AlertCircle size={14} className="text-yellow-400 flex-shrink-0" />
                Server settings require a restart to take effect. Edit your .env file or environment variables directly.
              </p>
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

function PhoneBridgeSection() {
  return (
    <Section title="Connect Your Phone" icon={Smartphone}>
      <div style={{ padding: 24, background: 'rgba(6,182,212,0.05)', border: '1px solid rgba(6,182,212,0.2)', borderRadius: 12 }}>
        <p className="text-xs text-feral-text-muted mb-4">
          For full phone capabilities (HealthKit, Health Connect, motion sensors, camera, voice),
          install the FERAL Node app and scan the QR code below.
        </p>
        <div className="flex gap-4 items-center flex-wrap">
          <div className="text-center">
            <img src="/api/devices/pair/qr" alt="Pairing QR" className="rounded-lg bg-white p-2" style={{ width: 200, height: 200 }} />
            <div className="text-[11px] mt-2 text-feral-text-muted">Scan with FERAL Node app</div>
          </div>
          <div className="flex flex-col gap-2">
            <a href="https://apps.apple.com/" target="_blank" rel="noopener noreferrer"
              className="px-4 py-2 bg-feral-card border border-feral-border rounded-lg text-feral-text text-xs no-underline hover:border-feral-border-bright transition">
              Download for iOS
            </a>
            <a href="https://play.google.com/" target="_blank" rel="noopener noreferrer"
              className="px-4 py-2 bg-feral-card border border-feral-border rounded-lg text-feral-text text-xs no-underline hover:border-feral-border-bright transition">
              Download for Android
            </a>
            <div className="text-[10px] text-feral-text-muted mt-2">
              Or run the hardware daemon: <code className="bg-feral-bg px-1.5 py-0.5 rounded font-mono text-[10px]">python -m feral_nodes.hardware_daemon</code>
            </div>
          </div>
        </div>
      </div>
    </Section>
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
    <div className={`flex items-center gap-3 bg-feral-card border rounded-xl px-4 py-3 ${
      device.connected ? 'border-green-500/30' : 'border-feral-border'
    }`}>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
        device.connected ? 'bg-green-500/10' : 'bg-white/5'
      }`}>
        <Icon size={20} className={device.connected ? 'text-green-400' : 'text-feral-text-muted'} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm truncate">{device.node_id}</div>
        <div className="text-xs text-feral-text-secondary">{device.type || 'unknown device'}</div>
      </div>
      <div className={`w-2.5 h-2.5 rounded-full ${device.connected ? 'bg-green-500' : 'bg-zinc-600'}`} />
    </div>
  );
}

function Section({ title, icon: Icon, children }) {
  return (
    <div className="bg-feral-card border border-feral-border rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Icon size={18} className="text-feral-accent" />
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
        {desc && <div className="text-xs text-feral-text-secondary mt-0.5">{desc}</div>}
      </div>
      <button
        onClick={() => onChange(!value)}
        className={`w-12 h-7 rounded-full transition-all flex items-center px-1 ${
          value ? 'bg-feral-accent justify-end' : 'bg-zinc-700 justify-start'
        }`}
      >
        <div className="w-5 h-5 bg-white rounded-full shadow transition-all" />
      </button>
    </div>
  );
}
