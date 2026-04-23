import React, { useCallback, useEffect, useState } from 'react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import EmptyState from '../ui/EmptyState';
import StatusDot from '../ui/StatusDot';
import CodeEditor from '../ui/CodeEditor';
import { SelfWorkspace } from '../components/SelfEditors';
import { apiFetch, apiJson } from '../lib/api';
import { API_BASE } from '../lib/config';

/**
 * Settings — thirteen real sections. Self is the first section users
 * expect to find for "about me / my agent's personality" and it embeds
 * the same IDENTITY / SOUL / MEMORY editors that live at /identity so
 * users never have to hunt through the ⌘K hub to find them.
 */

const SECTIONS = [
  'Self', 'General', 'Providers', 'Memory', 'Channels', 'Autonomy', 'Voice',
  'Twin', 'Security', 'Integrations', 'Sync', 'Handoff', 'Push', 'MCP',
];

export default function Settings() {
  const [section, setSection] = useState('Self');

  return (
    <div className="v2-page v2-page--split" data-testid="v2-marker">
      <aside className="v2-settings-nav">
        <Glass level={1} radius="lg" padding="sm">
          <ul className="v2-settings-list">
            {SECTIONS.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  className={`v2-settings-btn${section === s ? ' is-active' : ''}`}
                  onClick={() => setSection(s)}
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
        </Glass>
      </aside>
      <Pane title={section}>
        {section === 'Self' && <SelfSection />}
        {section === 'General' && <GeneralSection />}
        {section === 'Providers' && <ProvidersSection />}
        {section === 'Memory' && <MemorySection />}
        {section === 'Channels' && <ChannelsSection />}
        {section === 'Autonomy' && <AutonomySection />}
        {section === 'Voice' && <VoiceSection />}
        {section === 'Security' && <SecuritySection />}
        {section === 'Integrations' && <IntegrationsSection />}
        {section === 'Sync' && <SyncSection />}
        {section === 'Handoff' && <HandoffSection />}
        {section === 'Push' && <PushSection />}
        {section === 'MCP' && <McpSection />}
        {section === 'Twin' && <TwinSection />}
      </Pane>
    </div>
  );
}

function SelfSection() {
  return (
    <>
      <p className="v2-p v2-p--muted">
        Your agent's personality + what it knows about you.
        Same editors you'll find at <code>/identity</code>.
      </p>
      <SelfWorkspace defaultTab="identity" showIntro={false} />
    </>
  );
}

// ── Shared primitives ─────────────────────────────────────────

function useConfig() {
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);
  const refresh = useCallback(async () => {
    try { setConfig(await apiJson('/api/config')); } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const update = useCallback(async (sec, key, value) => {
    const r = await apiFetch('/api/config/update', {
      method: 'POST',
      body: JSON.stringify({ section: sec, key, value }),
    });
    if (!r.ok) throw new Error(`${r.status}`);
    await refresh();
  }, [refresh]);
  return { config, error, refresh, update };
}

function Row({ label, hint, children }) {
  return (
    <div className="v2-setting-row">
      <div className="v2-setting-label">
        <div>{label}</div>
        {hint && <div className="v2-setting-hint">{hint}</div>}
      </div>
      <div className="v2-setting-control">{children}</div>
    </div>
  );
}

function Toggle({ checked, disabled, onChange }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`v2-toggle${checked ? ' is-on' : ''}`}
    >
      <span className="v2-toggle-thumb" />
    </button>
  );
}

function Select({ value, options, onChange, disabled }) {
  return (
    <select className="v2-select" value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function Status({ tone = 'neutral', children }) {
  return <span className={`v2-chip v2-chip--${tone}`}>{children}</span>;
}

// ── General ───────────────────────────────────────────────────

function GeneralSection() {
  const { config, update } = useConfig();
  const [busy, setBusy] = useState('');
  if (!config) return <EmptyState title="Loading config…" />;
  const features = config.features || {};
  const featureRow = (key, label, hint) => (
    <Row label={label} hint={hint} key={key}>
      <Toggle
        checked={!!features[key]}
        disabled={busy === key}
        onChange={async (next) => { setBusy(key); try { await update('features', key, next); } finally { setBusy(''); } }}
      />
    </Row>
  );
  return (
    <div className="v2-setting-stack">
      <Row label="Version" hint="Current feral-ai build"><code className="v2-code-inline">{config.version || '—'}</code></Row>
      {featureRow('streaming', 'Streaming replies', 'Token-by-token output')}
      {featureRow('proactive', 'Proactive alerts', 'Brain surfaces things without being asked')}
      {featureRow('self_learning', 'Self-learning', 'Enables Tool Genesis + pattern learning')}
      {featureRow('multi_agent', 'Multi-agent', 'Lets orchestrator spawn specialist sub-agents')}
      {featureRow('vision', 'Vision loop', 'Periodic screen-captioning for ambient context')}
    </div>
  );
}

// ── Providers ─────────────────────────────────────────────────

function ProvidersSection() {
  const [status, setStatus] = useState(null);
  const [providers, setProviders] = useState([]);
  const [presets, setPresets] = useState([]);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null); // currently-edited provider card

  const refresh = useCallback(async () => {
    try {
      const [s, providersResp, presetsResp] = await Promise.all([
        apiJson('/api/llm/status').catch(() => null),
        apiJson('/api/llm/providers').catch(() => ({ providers: [] })),
        apiJson('/api/llm/presets').catch(() => ({ presets: [] })),
      ]);
      if (s) setStatus(s);
      setProviders(providersResp.providers || providersResp || []);
      setPresets(presetsResp.presets || []);
      setError(null);
    } catch (e) {
      setError(e?.message || 'failed to load provider catalog');
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const applyPreset = async (preset) => {
    await apiFetch('/api/llm/presets/apply', {
      method: 'POST',
      body: JSON.stringify({ preset }),
    });
    refresh();
  };

  return (
    <div className="v2-providers">
      {error && <div className="v2-chip v2-chip--error">{error}</div>}

      <div className="v2-providers-current">
        <div>
          <div className="v2-stat-label">Current provider</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <StatusDot tone={status?.available ? 'live' : 'warn'} pulse={!!status?.available} />
            <strong>{status?.provider || 'none'}</strong>
            <span className="v2-p v2-p--muted">{status?.model || ''}</span>
          </div>
          <div className="v2-p v2-p--muted v2-p--tiny">
            {status?.available
              ? 'Live inference backend — reconfigure via any card below.'
              : 'No available provider. Configure one below.'}
          </div>
        </div>
        <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh}>Refresh</button>
      </div>

      {presets.length > 0 && (
        <div className="v2-providers-presets">
          <div className="v2-stat-label" style={{ marginRight: 6 }}>Presets</div>
          {presets.map((p) => (
            <button
              key={p.id || p.preset}
              type="button"
              className="v2-btn"
              onClick={() => applyPreset(p.id || p.preset)}
            >
              {p.label || p.id || p.preset}
            </button>
          ))}
        </div>
      )}

      <div className="v2-providers-grid">
        {providers.map((p) => {
          const pid = p.id || p.provider_id;
          return (
            <ProviderCard
              key={pid}
              provider={{ ...p, provider_id: pid }}
              isCurrent={(status?.provider || '').toLowerCase() === (pid || '').toLowerCase()}
              isEditing={selected === pid}
              onEdit={() => setSelected(pid)}
              onCancel={() => setSelected(null)}
              onSaved={() => { setSelected(null); refresh(); }}
            />
          );
        })}
      </div>
    </div>
  );
}

function ProviderCard({ provider, isCurrent, isEditing, onEdit, onCancel, onSaved }) {
  const supportsLocal = !!provider.supports_local;
  const requiresKey = !!provider.requires_api_key;
  // `reachable` is null until the user probes; `configured` = has a key
  // (or no-key-required). Show that cleanly in the dot + label.
  const reachable = provider.reachable;
  const configured = !!provider.configured;
  const statusTone =
    reachable === true ? 'live'
      : reachable === false ? 'off'
      : configured ? 'warn'
      : requiresKey ? 'off'
      : 'neutral';
  const statusLabel =
    reachable === true ? 'ready'
      : reachable === false ? 'unreachable'
      : configured ? 'configured'
      : requiresKey ? 'needs key'
      : 'unconfigured';

  return (
    <Glass level={0} radius="md" padding="sm" className={`v2-provider-card${isCurrent ? ' is-current' : ''}`}>
      <div className="v2-provider-head">
        <div>
          <div className="v2-provider-name">{provider.display_name || provider.provider_id}</div>
          <div className="v2-p v2-p--tiny v2-p--muted">
            <code>{provider.provider_id}</code>
            {supportsLocal && <> · local</>}
            {!requiresKey && <> · no key required</>}
            {isCurrent && <> · <span style={{ color: 'var(--v2-accent)' }}>current</span></>}
          </div>
        </div>
        <div className="v2-provider-status">
          <StatusDot tone={statusTone} />
          <span className="v2-p v2-p--tiny">{statusLabel}</span>
        </div>
      </div>

      {isEditing ? (
        <ProviderForm provider={provider} onCancel={onCancel} onSaved={onSaved} />
      ) : (
        <div className="v2-provider-actions">
          <button type="button" className="v2-btn v2-btn--primary" onClick={onEdit}>
            {isCurrent ? 'Reconfigure' : 'Use this provider'}
          </button>
        </div>
      )}
    </Glass>
  );
}

function ProviderForm({ provider, onCancel, onSaved }) {
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelError, setModelError] = useState(null);
  const [selectedModel, setSelectedModel] = useState(provider.default_model || '');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState(provider.default_base_url || '');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);

  const loadModels = useCallback(async () => {
    setLoadingModels(true);
    setModelError(null);
    try {
      const d = await apiJson(`/api/llm/providers/${encodeURIComponent(provider.provider_id)}/models?live=true`);
      const list = d.models || d || [];
      setModels(list);
      if (list.length > 0 && !selectedModel) {
        setSelectedModel(list[0].id || list[0]);
      }
    } catch (e) {
      setModelError(e?.message || 'failed to fetch models');
    } finally {
      setLoadingModels(false);
    }
  }, [provider.provider_id, selectedModel]);

  useEffect(() => { loadModels(); }, [loadModels]);

  const save = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await apiFetch('/api/llm/config', {
        method: 'POST',
        body: JSON.stringify({
          provider: provider.provider_id,
          model: selectedModel || provider.default_model || 'gpt-4o-mini',
          api_key: apiKey || undefined,
          base_url: baseUrl || undefined,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body?.success === false) {
        setErr(body?.detail || body?.error || `${r.status}`);
        return;
      }
      const p = body.persisted || {};
      const warn = p.warnings || [];
      if (warn.length) {
        setMsg(`Saved — warning: ${warn.join('; ')}`);
      } else {
        setMsg('Saved and switched ✓');
      }
      setTimeout(() => onSaved(), 600);
    } catch (e) {
      setErr(e?.message || 'failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="v2-provider-form">
      {provider.requires_api_key && (
        <label className="v2-identity-field">
          <span className="v2-identity-field-label">{provider.credential_env_var || 'API key'}</span>
          <input
            className="v2-input"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={provider.configured ? 'leave blank to keep existing key' : 'paste new key'}
            autoComplete="off"
          />
        </label>
      )}

      {provider.supports_local && (
        <label className="v2-identity-field">
          <span className="v2-identity-field-label">Base URL</span>
          <input
            className="v2-input"
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={provider.default_base_url || 'http://localhost:1234/v1'}
          />
        </label>
      )}

      <div className="v2-identity-field">
        <span className="v2-identity-field-label">Model</span>
        <div className="v2-provider-model-row">
          <input
            className="v2-input"
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            placeholder={provider.default_model || 'gpt-4o-mini'}
            list={`models-${provider.provider_id}`}
          />
          <button type="button" className="v2-btn v2-btn--ghost" onClick={loadModels} disabled={loadingModels}>
            {loadingModels ? 'Loading…' : 'Refresh models'}
          </button>
          <datalist id={`models-${provider.provider_id}`}>
            {models.map((m, i) => {
              const id = typeof m === 'string' ? m : (m.id || m.name || '');
              return <option key={id || i} value={id}>{id}</option>;
            })}
          </datalist>
        </div>
        {loadingModels && <span className="v2-p v2-p--muted v2-p--tiny">Probing /models…</span>}
        {!loadingModels && models.length > 0 && (
          <span className="v2-p v2-p--muted v2-p--tiny">{models.length} model{models.length === 1 ? '' : 's'} available</span>
        )}
        {!loadingModels && models.length === 0 && !modelError && (
          <span className="v2-p v2-p--muted v2-p--tiny">No models returned — type any model id above to use.</span>
        )}
        {modelError && (
          <span className="v2-chip v2-chip--warn">{modelError}</span>
        )}
      </div>

      <div className="v2-provider-actions" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="v2-btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className="v2-btn v2-btn--primary" onClick={save} disabled={busy || !selectedModel}>
          {busy ? 'Saving…' : 'Save & switch'}
        </button>
      </div>
      {msg && <div className="v2-chip v2-chip--live">{msg}</div>}
      {err && <div className="v2-chip v2-chip--error">{err}</div>}
    </div>
  );
}

// ── Memory ────────────────────────────────────────────────────

function MemorySection() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try { setData(await apiJson('/api/memory/backend')); } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const switchTo = async (next) => {
    setBusy(true);
    try {
      const r = await apiFetch('/api/memory/backend', {
        method: 'POST',
        body: JSON.stringify({ backend: next }),
      });
      const body = await r.json();
      if (!body?.ok) setError(body?.error || 'switch failed');
      await refresh();
    } finally { setBusy(false); }
  };

  if (!data) return <EmptyState title={error || 'Loading memory status…'} />;

  return (
    <div className="v2-setting-stack">
      <Row label="Active backend"><Status tone="live">{data.backend}</Status></Row>
      {Object.entries(data.available || {}).map(([name, installed]) => (
        <Row
          key={name}
          label={name}
          hint={installed ? 'Installed' : `Run: pip install feral-ai[memory-${name}]`}
        >
          <button
            type="button"
            className={`v2-btn ${data.backend === name ? 'v2-btn--primary' : ''}`}
            disabled={busy || !installed || data.backend === name}
            onClick={() => switchTo(name)}
          >
            {data.backend === name ? 'In use' : installed ? 'Switch' : 'Not installed'}
          </button>
        </Row>
      ))}
      {error && <div className="v2-chip v2-chip--error">{error}</div>}
    </div>
  );
}

// ── Channels ──────────────────────────────────────────────────

function ChannelsSection() {
  const [stats, setStats] = useState(null);
  const [creds, setCreds] = useState({});
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => { apiJson('/api/channels').then(setStats).catch((e) => setError(e.message)); }, []);

  if (!stats) return <EmptyState title={error || 'Loading channels…'} />;
  const entries = Object.entries(stats.status_by_channel || stats.channels || {});

  const save = async (channel) => {
    setBusy(channel);
    try {
      const envKey = {
        telegram: 'FERAL_TELEGRAM_BOT_TOKEN',
        discord: 'FERAL_DISCORD_BOT_TOKEN',
        slack: 'FERAL_SLACK_BOT_TOKEN',
      }[channel] || `FERAL_${channel.toUpperCase()}_BOT_TOKEN`;
      await apiFetch('/api/config/credentials', {
        method: 'POST',
        body: JSON.stringify({ [envKey]: creds[channel] }),
      });
      await apiFetch('/api/channels/start', {
        method: 'POST',
        body: JSON.stringify({ type: channel, config: { bot_token: creds[channel], enabled: true } }),
      });
    } finally { setBusy(null); }
  };

  return (
    <div className="v2-setting-stack">
      <Row label="Active channels"><Status>{stats.active ?? entries.length}</Status></Row>
      {entries.map(([name, info]) => (
        <Row key={name} label={name} hint={info?.description || ''}>
          <Status tone={info?.connected ? 'live' : 'warn'}>{info?.connected ? 'connected' : 'disabled'}</Status>
        </Row>
      ))}
      {['telegram', 'discord', 'slack'].map((c) => (
        <Row key={c} label={`${c} token`} hint="Paste bot token and save to enable.">
          <input type="password" className="v2-input" value={creds[c] || ''} onChange={(e) => setCreds((s) => ({ ...s, [c]: e.target.value }))} placeholder="Bot token" />
          <button type="button" className="v2-btn" onClick={() => save(c)} disabled={busy === c || !creds[c]}>
            {busy === c ? 'Saving…' : 'Save + enable'}
          </button>
        </Row>
      ))}
    </div>
  );
}

// ── Autonomy ──────────────────────────────────────────────────

function AutonomySection() {
  const [mode, setMode] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { apiJson('/api/autonomy').then((d) => setMode(d.mode)); }, []);
  if (!mode) return <EmptyState title="Loading…" />;
  const tiers = [
    { id: 'strict', label: 'Strict', desc: 'Approval for every tool call. Safest, slowest.' },
    { id: 'hybrid', label: 'Hybrid', desc: 'Surfaces drafts for approval. Default.' },
    { id: 'loose', label: 'Loose', desc: 'Auto-promotes + auto-runs. Use for trusted environments.' },
  ];
  const set = async (next) => {
    setBusy(true);
    try {
      const r = await apiFetch('/api/autonomy', { method: 'POST', body: JSON.stringify({ mode: next }) });
      if (r.ok) setMode(next);
    } finally { setBusy(false); }
  };
  return (
    <div className="v2-setting-stack">
      <Row label="Current tier"><Status tone={mode === 'loose' ? 'warn' : 'live'}>{mode}</Status></Row>
      {tiers.map((t) => (
        <Row key={t.id} label={t.label} hint={t.desc}>
          <button type="button" className={`v2-btn ${mode === t.id ? 'v2-btn--primary' : ''}`} disabled={busy || mode === t.id} onClick={() => set(t.id)}>
            {mode === t.id ? 'Active' : 'Select'}
          </button>
        </Row>
      ))}
    </div>
  );
}

// ── Voice ─────────────────────────────────────────────────────

function VoiceSection() {
  const [status, setStatus] = useState(null);
  const [config, setConfig] = useState(null);
  const [busy, setBusy] = useState('');
  const [wakeWord, setWakeWord] = useState({ enabled: false, supported: true });

  const refresh = useCallback(async () => {
    const [s, c, ww] = await Promise.allSettled([
      apiJson('/api/voice/status'),
      apiJson('/api/config'),
      apiJson('/api/ambient/wake_word/status'),
    ]);
    if (s.status === 'fulfilled') setStatus(s.value);
    if (c.status === 'fulfilled') setConfig(c.value);
    if (ww.status === 'fulfilled') setWakeWord({ enabled: !!ww.value?.enabled, supported: ww.value?.supported !== false });
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  if (!status || !config) return <EmptyState title="Loading voice status…" />;
  const audio = config.audio || {};

  const updateAudio = async (key, value) => {
    setBusy(key);
    try {
      await apiFetch('/api/config/update', { method: 'POST', body: JSON.stringify({ section: 'audio', key, value }) });
      await refresh();
    } finally { setBusy(''); }
  };

  const toggleWake = async () => {
    const next = !wakeWord.enabled;
    await apiFetch('/api/ambient/wake_word/toggle', { method: 'POST', body: JSON.stringify({ enabled: next }) });
    refresh();
  };

  return (
    <div className="v2-setting-stack">
      <Row label="Realtime voice"><Status tone={status.realtime_available ? 'live' : 'warn'}>{status.realtime_available ? 'ready' : 'unavailable'}</Status></Row>
      <Row label="Local TTS/STT"><Status tone={status.audio_available ? 'live' : 'warn'}>{status.audio_available ? 'ready' : 'unavailable'}</Status></Row>
      <Row label="Active sessions"><Status>{status.active_realtime_sessions ?? 0}</Status></Row>
      <Row label="Wake word" hint={wakeWord.supported ? '' : 'Install feral-ai[wake] to enable.'}>
        <Toggle checked={!!wakeWord.enabled} disabled={!wakeWord.supported} onChange={toggleWake} />
      </Row>
      <Row label="STT provider">
        <Select
          value={audio.stt_provider || 'openai'}
          disabled={busy === 'stt_provider'}
          onChange={(v) => updateAudio('stt_provider', v)}
          options={[
            { value: 'openai', label: 'OpenAI Whisper' },
            { value: 'gemini', label: 'Gemini' },
            { value: 'local', label: 'Local Whisper' },
          ]}
        />
      </Row>
      <Row label="TTS voice">
        <input
          className="v2-input"
          defaultValue={audio.tts_voice || ''}
          onBlur={(e) => { if (e.target.value !== (audio.tts_voice || '')) updateAudio('tts_voice', e.target.value); }}
          placeholder="nova, alloy, shimmer, …"
        />
      </Row>
    </div>
  );
}

// ── Security ──────────────────────────────────────────────────

function SecuritySection() {
  return (
    <div className="v2-setting-stack" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <VaultSub />
      <PermissionsSub />
      <AuditSub />
      <PolicySub />
    </div>
  );
}

function VaultSub() {
  const [items, setItems] = useState([]);
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await apiJson('/api/security/vault');
      // Brain returns {keys: {NAME: {stored, fingerprint}, ...}} as a dict.
      // Also tolerate legacy array shapes.
      let entries = [];
      if (d?.keys && typeof d.keys === 'object' && !Array.isArray(d.keys)) {
        entries = Object.entries(d.keys).map(([name, meta]) => ({
          name,
          stored: meta?.stored ?? true,
          fingerprint: meta?.fingerprint || '',
        }));
      } else if (Array.isArray(d?.keys)) {
        entries = d.keys.map((k) => typeof k === 'string' ? { name: k } : k);
      } else if (Array.isArray(d)) {
        entries = d.map((k) => typeof k === 'string' ? { name: k } : k);
      }
      setItems(entries);
    } catch { setItems([]); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const store = async () => {
    setBusy(true);
    try {
      await apiFetch('/api/security/vault/store', {
        method: 'POST',
        body: JSON.stringify({ key_name: key, value }),
      });
      setKey(''); setValue('');
      refresh();
    } finally { setBusy(false); }
  };

  const remove = async (name) => {
    if (!window.confirm(`Remove ${name}? This deletes the stored secret.`)) return;
    await apiFetch(`/api/security/vault/${encodeURIComponent(name)}`, { method: 'DELETE' });
    refresh();
  };

  return (
    <Glass level={1} radius="md" padding="lg">
      <h3>Vault</h3>
      <p className="v2-p v2-p--muted">
        Encrypted at-rest storage for API keys + secrets. Values never leave
        the Brain or render in the UI — only the key name + a fingerprint.
      </p>
      <div className="v2-vault-list">
        {items.map((it) => (
          <div key={it.name} className="v2-vault-row">
            <code className="v2-vault-name">{it.name}</code>
            {it.fingerprint && (
              <code className="v2-vault-fp" title="Fingerprint">{it.fingerprint.slice(0, 12)}</code>
            )}
            <Status tone={it.stored ? 'live' : 'off'}>{it.stored ? 'stored' : 'empty'}</Status>
            <button
              type="button"
              className="v2-btn v2-btn--ghost"
              onClick={() => remove(it.name)}
            >
              Remove
            </button>
          </div>
        ))}
        {items.length === 0 && <div className="v2-p v2-p--muted">No stored keys yet.</div>}
      </div>
      <div className="v2-setting-stack" style={{ marginTop: 16 }}>
        <Row label="Key name"><input className="v2-input" value={key} onChange={(e) => setKey(e.target.value)} placeholder="OPENWEATHER_API_KEY" /></Row>
        <Row label="Value"><input type="password" className="v2-input" value={value} onChange={(e) => setValue(e.target.value)} /></Row>
        <Row label=""><button type="button" className="v2-btn v2-btn--primary" onClick={store} disabled={busy || !key || !value}>Store</button></Row>
      </div>
    </Glass>
  );
}

function PermissionsSub() {
  const [perms, setPerms] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try { setPerms(await apiJson('/api/security/permissions')); }
    catch { setPerms({}); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const setTier = async (tier) => {
    setBusy(true);
    try {
      await apiFetch('/api/security/permissions/update', {
        method: 'POST',
        body: JSON.stringify({ max_tier: tier }),
      });
      await refresh();
    } finally { setBusy(false); }
  };

  if (!perms) return <Glass level={1} radius="md" padding="lg"><EmptyState title="Loading…" /></Glass>;

  const tiers = Array.isArray(perms.tiers) ? perms.tiers : ['passive', 'active', 'privileged', 'dangerous'];
  const descs = perms.tier_descriptions || {};
  const current = perms.max_tier;

  return (
    <Glass level={1} radius="md" padding="lg">
      <h3>Permissions</h3>
      <p className="v2-p v2-p--muted">
        Max tier caps what every tool call can do. Lower tiers are safer — tools
        above this level are blocked until you raise it.
      </p>
      <div className="v2-setting-stack">
        <Row label="Current max tier">
          <Status tone={current === 'dangerous' ? 'error' : current === 'privileged' ? 'warn' : 'live'}>
            {current}
          </Status>
        </Row>
        {tiers.map((t) => (
          <Row key={t} label={t} hint={descs[t] || ''}>
            <button
              type="button"
              className={`v2-btn ${current === t ? 'v2-btn--primary' : ''}`}
              disabled={busy || current === t}
              onClick={() => setTier(t)}
            >
              {current === t ? 'Active' : 'Set'}
            </button>
          </Row>
        ))}
      </div>
    </Glass>
  );
}

function AuditSub() {
  const [log, setLog] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiJson('/api/security/audit')
      .then((d) => setLog(d?.entries || d?.log || (Array.isArray(d) ? d : [])))
      .catch(() => setLog([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Glass level={1} radius="md" padding="lg">
      <h3>Audit log</h3>
      <p className="v2-p v2-p--muted">Every vault retrieve / store / delete, timestamped.</p>
      {loading && <EmptyState title="Loading…" />}
      {!loading && log.length === 0 && <EmptyState title="No audit entries" />}
      {!loading && log.length > 0 && (
        <ul className="v2-audit-list">
          {log.slice(-40).reverse().map((e, i) => {
            const when = e.ts ? new Date(e.ts * 1000).toLocaleString() : '';
            const tone = e.action === 'store' ? 'live' : e.action === 'delete' ? 'error' : 'neutral';
            return (
              <li key={i} className="v2-audit-row">
                <Status tone={tone}>{e.action || 'event'}</Status>
                <code className="v2-audit-key">{e.key || '—'}</code>
                <span className="v2-audit-actor">{e.actor || ''}</span>
                <span className="v2-audit-time">{when}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Glass>
  );
}

function PolicySub() {
  const [policy, setPolicy] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    apiJson('/api/policy').then((d) => setPolicy(JSON.stringify(d, null, 2))).catch(() => setPolicy('{}'));
  }, []);
  const save = async () => {
    try {
      const parsed = JSON.parse(policy);
      await apiFetch('/api/policy/update', { method: 'POST', body: JSON.stringify(parsed) });
      setSaved(true);
      setDirty(false);
      setTimeout(() => setSaved(false), 2000);
    } catch { /* silent */ }
  };
  return (
    <Glass level={1} radius="md" padding="lg">
      <h3>Policy {dirty && <span className="v2-chip v2-chip--warn">unsaved</span>}{saved && <span className="v2-chip v2-chip--live">saved</span>}</h3>
      <p className="v2-p v2-p--muted">
        The Brain's safety policy as JSON — network allowlists, auto-approve
        categories, tier gates. Saves to the running Brain immediately.
      </p>
      <CodeEditor value={policy} onChange={(v) => { setPolicy(v); setDirty(true); }} rows={12} language="json" />
      <div className="v2-forge-actions"><button type="button" className="v2-btn v2-btn--primary" onClick={save} disabled={!dirty}>Save policy</button></div>
    </Glass>
  );
}

// ── Integrations ──────────────────────────────────────────────

function IntegrationsSection() {
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try { const d = await apiJson('/api/integrations'); setProviders(d.providers || d.integrations || d || []); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const connect = (id) => {
    window.open(`${API_BASE}/api/oauth/authorize/${encodeURIComponent(id)}`, '_blank', 'width=520,height=640');
  };

  const disconnect = async (id) => {
    await apiFetch(`/api/integrations/disconnect/${encodeURIComponent(id)}`, { method: 'POST' });
    refresh();
  };

  if (loading) return <EmptyState title="Loading…" />;

  return (
    <div className="v2-setting-stack">
      {providers.length === 0 && <EmptyState title="No integrations configured" />}
      {providers.map((p) => (
        <Row key={p.id || p.provider_id} label={p.name || p.id} hint={p.description}>
          <Status tone={p.connected ? 'live' : 'off'}>{p.connected ? 'connected' : 'disconnected'}</Status>
          {p.connected
            ? <button type="button" className="v2-btn" onClick={() => disconnect(p.id || p.provider_id)}>Disconnect</button>
            : <button type="button" className="v2-btn v2-btn--primary" onClick={() => connect(p.id || p.provider_id)}>Connect</button>
          }
        </Row>
      ))}
    </div>
  );
}

// ── Sync ──────────────────────────────────────────────────────

function SyncSection() {
  const [status, setStatus] = useState(null);
  const [importMsg, setImportMsg] = useState(null);

  useEffect(() => { apiJson('/api/sync/status').then(setStatus).catch(() => setStatus({})); }, []);

  const doImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportMsg('Uploading…');
    try {
      const text = await file.text();
      const body = JSON.parse(text);
      const r = await apiFetch('/api/sync/import', { method: 'POST', body: JSON.stringify(body) });
      setImportMsg(r.ok ? `Imported ${file.name}` : `Failed: ${r.status}`);
    } catch (err) {
      setImportMsg(`Failed: ${err.message}`);
    }
  };

  if (!status) return <EmptyState title="Loading sync status…" />;

  const peers = Array.isArray(status.peers) ? status.peers : [];

  return (
    <div className="v2-setting-stack">
      <p className="v2-p v2-p--muted">
        FERAL's memory replicates across your paired devices via a
        conflict-free data structure (CRDT). No central server — peers
        merge directly. Pair a second device to start syncing.
      </p>
      <Row label="Engine" hint="Sync subsystem status">
        <Status tone={status.enabled ? 'live' : 'off'}>
          {status.enabled ? 'enabled' : 'disabled'}
        </Status>
        <Status tone={status.running ? 'live' : 'off'}>
          {status.running ? 'running' : 'stopped'}
        </Status>
      </Row>
      <Row label="Node ID" hint="This device's stable identifier">
        <code className="v2-code-inline">{status.node_id || '—'}</code>
      </Row>
      <Row label="Peer count" hint={peers.length === 0 ? 'No other devices paired yet.' : undefined}>
        <Status tone={peers.length > 0 ? 'live' : 'neutral'}>{status.peer_count ?? peers.length}</Status>
      </Row>
      {peers.length > 0 && (
        <Row label="Peers">
          <div className="v2-skill-card-phrases">
            {peers.map((p) => (
              <span key={typeof p === 'string' ? p : p.id} className="v2-chip">
                {typeof p === 'string' ? p : (p.name || p.id)}
              </span>
            ))}
          </div>
        </Row>
      )}
      <Row label="WAL entries" hint="Write-ahead log — every change awaiting replication">
        <code className="v2-code-inline">{status.wal_entries ?? 0}</code>
      </Row>
      {status.vector_clock && Object.keys(status.vector_clock).length > 0 && (
        <Row label="Vector clock" hint="Causal ordering per peer">
          <details className="v2-vault-details">
            <summary>{Object.keys(status.vector_clock).length} entries</summary>
            <pre className="v2-code">{JSON.stringify(status.vector_clock, null, 2).slice(0, 800)}</pre>
          </details>
        </Row>
      )}
      <Row label="Export" hint="Download CRDT state for backup or manual sync">
        <a className="v2-btn" href={`${API_BASE}/api/sync/export`} target="_blank" rel="noreferrer">Download JSON</a>
      </Row>
      <Row label="Import" hint="Upload a previously exported CRDT state">
        <input type="file" accept="application/json" onChange={doImport} className="v2-input" />
      </Row>
      {importMsg && <div className="v2-chip v2-chip--live">{importMsg}</div>}
    </div>
  );
}

// ── Handoff ───────────────────────────────────────────────────

function HandoffSection() {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    apiJson('/api/handoff/devices')
      .then((d) => setDevices(d?.devices || (Array.isArray(d) ? d : [])))
      .catch(() => setDevices([]))
      .finally(() => setLoading(false));
  }, []);

  const handoff = async (target) => {
    setMsg('Handing off…');
    try {
      const r = await apiFetch('/api/handoff', {
        method: 'POST',
        body: JSON.stringify({ target }),
      });
      setMsg(r.ok ? `Handed off to ${target}` : `Failed: ${r.status}`);
    } catch (err) {
      setMsg(`Failed: ${err.message}`);
    }
  };

  return (
    <div className="v2-setting-stack">
      <p className="v2-p v2-p--muted">
        Handoff transfers your active FERAL session to another paired device.
        Start a conversation on your Mac, hand it off to your phone when you
        leave — the conversation context, active skills, and pending tool
        calls follow you. Requires at least two devices paired to this Brain.
      </p>
      {loading && <EmptyState title="Loading targets…" />}
      {!loading && devices.length === 0 && (
        <EmptyState
          title="No other devices paired yet"
          hint="Pair your phone, tablet, or another laptop to unlock handoff."
          action={<a href="/v2/devices" className="v2-btn v2-btn--primary">Open Devices</a>}
        />
      )}
      {devices.map((d) => (
        <Row key={d.id || d.device_id} label={d.name || d.device_id} hint={d.last_seen ? `Last seen ${d.last_seen}` : ''}>
          <button
            type="button"
            className="v2-btn v2-btn--primary"
            onClick={() => handoff(d.id || d.device_id)}
          >
            Hand off
          </button>
        </Row>
      ))}
      {msg && <div className="v2-chip v2-chip--live">{msg}</div>}
    </div>
  );
}

// ── Push ──────────────────────────────────────────────────────

function PushSection() {
  const [platform, setPlatform] = useState('apns');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const register = async () => {
    setBusy(true);
    try {
      const r = await apiFetch('/api/push/register', {
        method: 'POST',
        body: JSON.stringify({ platform, token }),
      });
      setMsg(r.ok ? 'Registered ✓' : `Failed: ${r.status}`);
    } finally { setBusy(false); }
  };

  const testSend = async () => {
    setBusy(true);
    try {
      await apiFetch('/api/push/send', {
        method: 'POST',
        body: JSON.stringify({ title: 'FERAL', body: 'Test push from Settings', platform }),
      });
      setMsg('Test push sent.');
    } finally { setBusy(false); }
  };

  return (
    <div className="v2-setting-stack">
      <Row label="Platform">
        <Select value={platform} onChange={setPlatform} options={[
          { value: 'apns', label: 'APNs (iOS)' },
          { value: 'fcm', label: 'FCM (Android)' },
        ]} />
      </Row>
      <Row label="Device token">
        <input className="v2-input" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Paste APNs / FCM token" />
      </Row>
      <Row label="">
        <button type="button" className="v2-btn v2-btn--primary" onClick={register} disabled={busy || !token}>Register</button>
        <button type="button" className="v2-btn" onClick={testSend} disabled={busy}>Send test</button>
      </Row>
      {msg && <div className="v2-chip v2-chip--live">{msg}</div>}
    </div>
  );
}

// ── MCP ───────────────────────────────────────────────────────

function McpSection() {
  const [status, setStatus] = useState(null);
  const [registry, setRegistry] = useState([]);
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);

  const refresh = useCallback(async () => {
    const [s, r, t] = await Promise.allSettled([
      apiJson('/api/mcp/status'),
      apiJson('/api/mcp/registry'),
      apiJson('/api/mcp/tools'),
    ]);
    if (s.status === 'fulfilled') setStatus(s.value);
    if (r.status === 'fulfilled') setRegistry(r.value?.servers || []);
    if (t.status === 'fulfilled') setTools(t.value?.tools || []);
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const connect = async (server) => {
    setBusy(server.id);
    setMsg(null);
    try {
      const body = {
        name: server.id,
        command: server.command,
        args: server.args,
        env: server.env,
      };
      const r = await apiFetch('/api/mcp/connect', { method: 'POST', body: JSON.stringify(body) });
      const data = await r.json().catch(() => ({}));
      setMsg(data?.success ? `${server.name} connected — ${data.tools} tools` : (data?.error || `Failed: ${r.status}`));
      refresh();
    } finally { setBusy(null); }
  };

  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); setMsg('Copied'); setTimeout(() => setMsg(null), 1500); } catch { /* silent */ }
  };

  if (loading) return <EmptyState title="Loading MCP…" />;

  const server = status?.server || {};
  const client = status?.client || {};

  return (
    <div className="v2-setting-stack">
      <p className="v2-p v2-p--muted">
        Model Context Protocol lets FERAL consume tools from external apps
        (GitHub, Filesystem, Slack, etc.) and lets external apps consume
        FERAL's skills via <code className="v2-code-inline">POST /mcp</code>.
      </p>
      <Row label="Server" hint="Tools FERAL exposes to external MCP clients">
        <Status tone="live">{server.tools_exposed ?? 0} tools</Status>
      </Row>
      <Row label="Client" hint="External MCP servers FERAL is consuming">
        <Status tone={client.servers_connected > 0 ? 'live' : 'off'}>
          {client.servers_connected ?? 0} servers
        </Status>
        <Status tone="neutral">{client.total_tools ?? 0} tools</Status>
      </Row>

      <div className="v2-p" style={{ marginTop: 8, fontWeight: 600 }}>Registered servers</div>
      {registry.length === 0 && <EmptyState title="No MCP servers in registry" />}
      <div className="v2-mcp-grid">
        {registry.map((s) => (
          <Glass key={s.id} level={0} radius="md" padding="md" className="v2-mcp-card">
            <header className="v2-mcp-head">
              <h3 className="v2-mcp-name">{s.name}</h3>
              <span className="v2-chip v2-chip--muted">{s.category || '—'}</span>
            </header>
            <p className="v2-p v2-p--muted">{s.description}</p>
            <div className="v2-mcp-chips">
              <Status tone={s.installed ? 'live' : 'off'}>
                {s.installed ? 'installed' : 'not installed'}
              </Status>
              <Status tone={s.configured ? 'live' : 'warn'}>
                {s.configured ? 'configured' : 'unconfigured'}
              </Status>
              <Status tone={s.connected ? 'live' : 'off'}>
                {s.connected ? 'connected' : 'disconnected'}
              </Status>
              {s.ready && <Status tone="live">ready</Status>}
            </div>
            {!s.installed && s.install_hint && (
              <div className="v2-mcp-hint">
                <div className="v2-p v2-p--tiny">Install:</div>
                <button
                  type="button"
                  className="v2-code v2-code--copyable"
                  onClick={() => copy(s.install_hint)}
                  title="Click to copy"
                >
                  {s.install_hint}
                </button>
              </div>
            )}
            {s.env && Object.keys(s.env).length > 0 && (
              <div className="v2-mcp-env">
                <div className="v2-p v2-p--tiny">Env:</div>
                <div className="v2-skill-card-phrases">
                  {Object.keys(s.env).map((k) => (
                    <span key={k} className={`v2-chip ${s.env[k] ? 'v2-chip--live' : 'v2-chip--warn'}`}>{k}</span>
                  ))}
                </div>
              </div>
            )}
            <div className="v2-forge-actions">
              {s.connected ? (
                <Status tone="live">in use</Status>
              ) : s.installed && s.ready ? (
                <button
                  type="button"
                  className="v2-btn v2-btn--primary"
                  disabled={busy === s.id}
                  onClick={() => connect(s)}
                >
                  {busy === s.id ? 'Connecting…' : 'Connect'}
                </button>
              ) : (
                <Status tone="neutral">needs setup</Status>
              )}
            </div>
          </Glass>
        ))}
      </div>

      {tools.length > 0 && (
        <details className="v2-vault-details">
          <summary>Connected tools ({tools.length})</summary>
          <ul className="v2-mem-list" style={{ marginTop: 8 }}>
            {tools.map((t, i) => (
              <li key={t.name || i}>
                <Glass level={0} radius="sm" padding="sm">
                  <div className="v2-flow-card-head">
                    <code className="v2-flow-card-title">{t.name}</code>
                    <span className="v2-chip v2-chip--muted">{t.server || ''}</span>
                  </div>
                  {t.description && <div className="v2-p v2-p--muted">{t.description}</div>}
                </Glass>
              </li>
            ))}
          </ul>
        </details>
      )}

      {msg && <div className="v2-chip v2-chip--live">{msg}</div>}
    </div>
  );
}


// ── Twin & Delegation ─────────────────────────────────────────

const TWIN_DOMAINS = [
  { id: 'respond_imessage', label: 'Respond to iMessage' },
  { id: 'draft_email', label: 'Draft email' },
  { id: 'reply_slack', label: 'Reply on Slack' },
  { id: 'reply_telegram', label: 'Reply on Telegram' },
  { id: 'reply_whatsapp', label: 'Reply on WhatsApp' },
  { id: 'schedule_meeting', label: 'Schedule meetings' },
  { id: 'buy_groceries', label: 'Buy groceries' },
  { id: 'summarise_reading', label: 'Summarise readings' },
  { id: 'post_journal', label: 'Post to journal' },
];

function TwinSection() {
  const [policies, setPolicies] = useState({});
  const [pending, setPending] = useState([]);
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const pols = await apiJson('/api/twin/policies').catch(() => ({ policies: [] }));
      const map = {};
      for (const p of (pols.policies || [])) map[p.domain] = p;
      setPolicies(map);
      const approvals = await apiJson('/api/twin/approvals?status=pending').catch(() => ({ approvals: [] }));
      setPending(approvals.approvals || []);
      const stats = await apiJson('/api/supervisor/stats').catch(() => null);
      if (stats) setPaused(!!stats.paused);
    } catch (e) {
      setErr(e?.message || 'failed to load twin state');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const upsert = async (domain, patch) => {
    const current = policies[domain] || {
      domain,
      mode: 'draft_only',
      time_windows: [],
      max_per_day: 10,
      requires_user_online: false,
    };
    const body = { ...current, ...patch, domain };
    await apiFetch('/api/twin/policies', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    refresh();
  };

  const revoke = async (domain) => {
    await apiFetch(`/api/twin/policies/${encodeURIComponent(domain)}`, { method: 'DELETE' });
    refresh();
  };

  const resolveApproval = async (id, verdict) => {
    await apiFetch(`/api/twin/approvals/${encodeURIComponent(id)}/${verdict}`, { method: 'POST' });
    refresh();
  };

  const togglePause = async () => {
    await apiFetch('/api/supervisor/pause', {
      method: 'POST',
      body: JSON.stringify({ paused: !paused }),
    });
    refresh();
  };

  return (
    <div className="v2-twin-section">
      <p className="v2-p v2-p--muted">
        Let the digital twin act for you — one toggle per domain. Draft-only keeps
        every action in the approval queue below; auto-send fires immediately
        within the window + daily cap. The big red button pauses every twin call
        and every orchestrator dispatch at once.
      </p>

      <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          type="button"
          className={`v2-btn ${paused ? 'v2-btn--primary' : ''}`}
          onClick={togglePause}
        >
          {paused ? 'Resume all actions' : 'Pause all actions'}
        </button>
        <span className="v2-p v2-p--muted v2-p--tiny">
          Kill switch — routes through <code>/api/supervisor/pause</code>.
        </span>
      </div>

      {err && <div className="v2-chip v2-chip--error" style={{ marginTop: 8 }}>{err}</div>}

      <div className="v2-twin-domains">
        {TWIN_DOMAINS.map(({ id, label }) => {
          const p = policies[id];
          const mode = p?.mode || 'off';
          const windows = (p?.time_windows || []).join(', ');
          const cap = p?.max_per_day ?? 10;
          return (
            <Glass key={id} level={0} radius="md" padding="sm" className="v2-twin-domain">
              <div className="v2-twin-domain-head">
                <div>
                  <div className="v2-twin-domain-label">{label}</div>
                  <div className="v2-p v2-p--tiny v2-p--muted">
                    <code>{id}</code> · {mode === 'off' ? 'not configured' : `${mode} · cap ${cap}/day`}{windows ? ` · ${windows}` : ''}
                  </div>
                </div>
                <div className="v2-twin-domain-actions">
                  <button type="button" className={`v2-btn ${mode === 'draft_only' ? 'v2-btn--primary' : ''}`} onClick={() => upsert(id, { mode: 'draft_only' })} disabled={busy}>Draft</button>
                  <button type="button" className={`v2-btn ${mode === 'auto_send' ? 'v2-btn--primary' : ''}`} onClick={() => upsert(id, { mode: 'auto_send' })} disabled={busy}>Auto</button>
                  <button type="button" className={`v2-btn ${mode === 'disabled' ? 'v2-btn--primary' : ''}`} onClick={() => upsert(id, { mode: 'disabled' })} disabled={busy}>Off</button>
                  {p && <button type="button" className="v2-btn v2-btn--ghost" onClick={() => revoke(id)} disabled={busy}>Clear</button>}
                </div>
              </div>
            </Glass>
          );
        })}
      </div>

      <div style={{ marginTop: 18 }}>
        <h3 style={{ margin: 0, fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--v2-text-secondary)' }}>
          Pending approvals
        </h3>
        {pending.length === 0 ? (
          <p className="v2-p v2-p--muted" style={{ marginTop: 6 }}>Queue is empty.</p>
        ) : (
          <ul className="v2-twin-approvals">
            {pending.map((row) => (
              <li key={row.approval_id}>
                <Glass level={0} radius="md" padding="sm">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontWeight: 600 }}>{row.domain} · {row.action}</div>
                      <div className="v2-p v2-p--tiny v2-p--muted">
                        queued {new Date((row.created_at || 0) * 1000).toLocaleString()}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button type="button" className="v2-btn v2-btn--primary" onClick={() => resolveApproval(row.approval_id, 'approve')}>Approve</button>
                      <button type="button" className="v2-btn" onClick={() => resolveApproval(row.approval_id, 'reject')}>Reject</button>
                    </div>
                  </div>
                  {row.context && Object.keys(row.context).length > 0 && (
                    <pre className="v2-publish-error" style={{ color: 'var(--v2-text-secondary)' }}>
                      {JSON.stringify(row.context, null, 2)}
                    </pre>
                  )}
                </Glass>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
