import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, ChevronRight } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import StatusDot from '../ui/StatusDot';
import PairDeviceModal from '../components/PairDeviceModal';
import { apiFetch } from '../lib/api';

/**
 * SetupWizard — runs on first boot when /api/setup/status returns
 * setup_complete=false. Walks the user through identity, LLM provider,
 * preset, optional channels, first device pair, then marks complete.
 */
const STEPS = [
  { id: 'identity', label: 'Identity' },
  { id: 'llm', label: 'LLM provider' },
  { id: 'preset', label: 'Model preset' },
  { id: 'channels', label: 'Channels' },
  { id: 'device', label: 'Pair device' },
  { id: 'done', label: 'Ready' },
];

export default function SetupWizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState('identity');
  const [name, setName] = useState('');
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  const [provider, setProvider] = useState('openai');
  const [apiKey, setApiKey] = useState('');
  const [validation, setValidation] = useState(null);
  const [preset, setPreset] = useState('');
  const [chanTokens, setChanTokens] = useState({ telegram: '', discord: '', slack: '' });
  const [showPair, setShowPair] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const next = () => {
    const i = STEPS.findIndex((s) => s.id === step);
    if (i < STEPS.length - 1) setStep(STEPS[i + 1].id);
  };

  const saveIdentity = async () => {
    setBusy(true);
    try {
      await apiFetch('/api/identity', {
        method: 'POST',
        body: JSON.stringify({ name, timezone }),
      });
      next();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const validateKey = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch('/api/config/validate-key', {
        method: 'POST',
        body: JSON.stringify({ provider, api_key: apiKey }),
      });
      const body = await r.json();
      setValidation(body);
      if (body.valid || body.ok) {
        await apiFetch('/api/config/credentials', {
          method: 'POST',
          body: JSON.stringify({
            [`${provider.toUpperCase()}_API_KEY`]: apiKey,
          }),
        });
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const applyPreset = async () => {
    if (!preset) { next(); return; }
    setBusy(true);
    try {
      await apiFetch('/api/llm/presets/apply', {
        method: 'POST',
        body: JSON.stringify({ preset }),
      });
      next();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const saveChannels = async () => {
    setBusy(true);
    try {
      const creds = {};
      if (chanTokens.telegram) creds.FERAL_TELEGRAM_BOT_TOKEN = chanTokens.telegram;
      if (chanTokens.discord) creds.FERAL_DISCORD_BOT_TOKEN = chanTokens.discord;
      if (chanTokens.slack) creds.FERAL_SLACK_BOT_TOKEN = chanTokens.slack;
      if (Object.keys(creds).length) {
        await apiFetch('/api/config/credentials', {
          method: 'POST',
          body: JSON.stringify(creds),
        });
      }
      next();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const finish = async () => {
    setBusy(true);
    try {
      await apiFetch('/api/setup/complete', { method: 'POST', body: JSON.stringify({}) });
      navigate('/');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker" style={{ maxWidth: 720 }}>
      <Pane title="Welcome to FERAL">
        <p className="v2-p v2-p--muted">
          Six quick steps and you're in. You can change any of this later from Settings.
        </p>
        <div className="v2-wizard-steps">
          {STEPS.map((s, i) => {
            const curr = STEPS.findIndex((x) => x.id === step);
            const done = i < curr;
            const active = i === curr;
            return (
              <div key={s.id} className={`v2-wizard-step${active ? ' is-active' : ''}${done ? ' is-done' : ''}`}>
                <StatusDot tone={done ? 'live' : active ? 'warn' : 'off'} />
                <span>{i + 1}. {s.label}</span>
              </div>
            );
          })}
        </div>
      </Pane>

      {step === 'identity' && (
        <Pane title="Identity">
          <div className="v2-setting-stack">
            <label className="v2-setting-row">
              <div className="v2-setting-label"><div>Your name</div></div>
              <div className="v2-setting-control"><input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Omar" /></div>
            </label>
            <label className="v2-setting-row">
              <div className="v2-setting-label"><div>Timezone</div></div>
              <div className="v2-setting-control"><input className="v2-input" value={timezone} onChange={(e) => setTimezone(e.target.value)} /></div>
            </label>
          </div>
          <div className="v2-forge-actions">
            <button type="button" className="v2-btn v2-btn--primary" onClick={saveIdentity} disabled={busy || !name.trim()}>
              Continue <ChevronRight size={13} />
            </button>
          </div>
        </Pane>
      )}

      {step === 'llm' && (
        <Pane title="LLM provider + API key">
          <div className="v2-setting-stack">
            <label className="v2-setting-row">
              <div className="v2-setting-label"><div>Provider</div></div>
              <div className="v2-setting-control">
                <select className="v2-select" value={provider} onChange={(e) => setProvider(e.target.value)}>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="gemini">Gemini</option>
                  <option value="groq">Groq</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="ollama">Ollama (local, no key)</option>
                </select>
              </div>
            </label>
            {provider !== 'ollama' && (
              <label className="v2-setting-row">
                <div className="v2-setting-label"><div>API key</div></div>
                <div className="v2-setting-control"><input type="password" className="v2-input" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></div>
              </label>
            )}
          </div>
          {validation && (
            <div className={`v2-chip v2-chip--${(validation.valid || validation.ok) ? 'live' : 'error'}`}>
              {(validation.valid || validation.ok) ? 'Key validated ✓' : (validation.message || 'Invalid')}
            </div>
          )}
          <div className="v2-forge-actions">
            {provider !== 'ollama' && (
              <button type="button" className="v2-btn" onClick={validateKey} disabled={busy || !apiKey.trim()}>Validate key</button>
            )}
            <button type="button" className="v2-btn v2-btn--primary" onClick={next} disabled={busy}>
              Continue <ChevronRight size={13} />
            </button>
          </div>
        </Pane>
      )}

      {step === 'preset' && (
        <Pane title="Model preset">
          <p className="v2-p v2-p--muted">Pick a one-click setup, or skip to use provider defaults.</p>
          <div className="v2-setting-stack">
            {['', 'openai_fast', 'openai_quality', 'anthropic_quality', 'ollama_local', 'ollama_vision'].map((p) => (
              <label key={p} className="v2-setting-row">
                <div className="v2-setting-label"><div>{p || 'Skip (use provider defaults)'}</div></div>
                <div className="v2-setting-control">
                  <input type="radio" name="preset" value={p} checked={preset === p} onChange={(e) => setPreset(e.target.value)} />
                </div>
              </label>
            ))}
          </div>
          <div className="v2-forge-actions">
            <button type="button" className="v2-btn v2-btn--primary" onClick={applyPreset} disabled={busy}>
              Continue <ChevronRight size={13} />
            </button>
          </div>
        </Pane>
      )}

      {step === 'channels' && (
        <Pane title="Messaging channels (optional)">
          <p className="v2-p v2-p--muted">Drop tokens for any channels you want. Skip any you don't use.</p>
          <div className="v2-setting-stack">
            {['telegram', 'discord', 'slack'].map((c) => (
              <label key={c} className="v2-setting-row">
                <div className="v2-setting-label"><div>{c}</div></div>
                <div className="v2-setting-control"><input type="password" className="v2-input" value={chanTokens[c]} onChange={(e) => setChanTokens((s) => ({ ...s, [c]: e.target.value }))} placeholder="Bot token" /></div>
              </label>
            ))}
          </div>
          <div className="v2-forge-actions">
            <button type="button" className="v2-btn v2-btn--primary" onClick={saveChannels} disabled={busy}>
              Continue <ChevronRight size={13} />
            </button>
          </div>
        </Pane>
      )}

      {step === 'device' && (
        <Pane title="Pair your first device">
          <p className="v2-p v2-p--muted">
            Optional but recommended. Pairing now gives FERAL access to health data,
            push notifications, and device-bound actuators.
          </p>
          <div className="v2-forge-actions">
            <button type="button" className="v2-btn" onClick={next}>Skip for now</button>
            <button type="button" className="v2-btn v2-btn--primary" onClick={() => setShowPair(true)}>
              Pair device
            </button>
          </div>
        </Pane>
      )}

      {step === 'done' && (
        <Pane title="All set">
          <Glass level={1} radius="md" padding="md">
            <div className="v2-stat-label">You're ready to go</div>
            <p className="v2-p" style={{ marginTop: 8 }}>
              FERAL is running locally. Open Chat to say hi, Dashboard for a live overview,
              or the Dock for the full tool set.
            </p>
          </Glass>
          <div className="v2-forge-actions">
            <button type="button" className="v2-btn v2-btn--primary" onClick={finish} disabled={busy}>
              <Check size={13} /> Finish setup
            </button>
          </div>
        </Pane>
      )}

      {error && <div className="v2-chip v2-chip--error">{error}</div>}

      <PairDeviceModal
        open={showPair}
        onClose={() => setShowPair(false)}
        onPaired={() => { setShowPair(false); next(); }}
      />
    </div>
  );
}
