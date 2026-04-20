import React, { useCallback, useEffect, useState } from 'react';
import { Users, Plus, ThumbsUp, ThumbsDown, RefreshCw } from 'lucide-react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import Modal from '../ui/Modal';
import Tabs from '../ui/Tabs';
import EmptyState from '../ui/EmptyState';
import { apiJson, apiFetch } from '../lib/api';

/**
 * Agents — Agent Mitosis specialists. Brain routes:
 *   GET  /api/agents/list
 *   GET  /api/agents/proposals
 *   POST /api/agents/spawn
 *   POST /api/agents/feedback
 *   GET  /api/agents/stats
 */
export default function Agents() {
  const [tab, setTab] = useState('specialists');
  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title="Agent Mitosis"
        actions={(
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { id: 'specialists', label: 'Specialists' },
              { id: 'proposals', label: 'Proposals' },
              { id: 'stats', label: 'Stats' },
            ]}
          />
        )}
      >
        <p className="v2-p v2-p--muted">
          Permanent specialist sub-agents with their own system prompt + narrow tool permissions.
          Proposals surface when FERAL sees a recurring task pattern.
        </p>
      </Pane>

      {tab === 'specialists' && <SpecialistsTab />}
      {tab === 'proposals' && <ProposalsTab />}
      {tab === 'stats' && <StatsTab />}
    </div>
  );
}

function SpecialistsTab() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showSpawn, setShowSpawn] = useState(false);
  const [skills, setSkills] = useState([]);

  const refresh = useCallback(async () => {
    try {
      const [a, s] = await Promise.allSettled([
        apiJson('/api/agents/list'),
        apiJson('/skills'),
      ]);
      if (a.status === 'fulfilled') setAgents(a.value?.agents || a.value?.specialists || a.value || []);
      if (s.status === 'fulfilled') setSkills(s.value?.skills || s.value || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const feedback = async (id, score) => {
    try {
      await apiFetch('/api/agents/feedback', {
        method: 'POST',
        body: JSON.stringify({ agent_id: id, score }),
      });
      refresh();
    } catch { /* silent */ }
  };

  return (
    <>
      <Pane
        title={`Specialists (${agents.length})`}
        actions={(
          <>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh}><RefreshCw size={13} /></button>
            <button type="button" className="v2-btn v2-btn--primary" onClick={() => setShowSpawn(true)}>
              <Plus size={13} /> Spawn specialist
            </button>
          </>
        )}
      >
        {loading && <EmptyState title="Loading…" />}
        {!loading && agents.length === 0 && (
          <EmptyState
            title="No specialists yet"
            hint="Spawn one manually or wait for Agent Mitosis to propose one based on recurring task patterns."
            action={<button type="button" className="v2-btn v2-btn--primary" onClick={() => setShowSpawn(true)}>Spawn first specialist</button>}
          />
        )}
        <div className="v2-skills-grid">
          {agents.map((a) => (
            <Glass key={a.agent_id || a.id} level={0} radius="md" padding="md" className="v2-skill-card">
              <header className="v2-skill-card-head">
                <h3 className="v2-skill-card-name">{a.name || a.agent_id}</h3>
                <code className="v2-skill-card-id">{a.agent_id || a.id}</code>
              </header>
              {a.description && <p className="v2-p v2-p--muted">{a.description}</p>}
              <div className="v2-skill-card-meta">
                {a.tasks_completed != null && <span className="v2-chip">{a.tasks_completed} tasks</span>}
                {a.satisfaction_score != null && <span className="v2-chip">{(a.satisfaction_score * 100).toFixed(0)}% satisfaction</span>}
                {a.schedule && <span className="v2-chip v2-chip--muted">{a.schedule}</span>}
              </div>
              {a.tool_permissions && Array.isArray(a.tool_permissions) && (
                <div className="v2-skill-card-phrases">
                  {a.tool_permissions.slice(0, 5).map((p) => (
                    <span key={p} className="v2-chip v2-chip--muted">{p}</span>
                  ))}
                </div>
              )}
              <div className="v2-forge-actions">
                <button type="button" className="v2-btn" onClick={() => feedback(a.agent_id || a.id, 1)}><ThumbsUp size={12} /></button>
                <button type="button" className="v2-btn" onClick={() => feedback(a.agent_id || a.id, -1)}><ThumbsDown size={12} /></button>
              </div>
            </Glass>
          ))}
        </div>
      </Pane>

      {showSpawn && <SpawnModal skills={skills} onClose={() => setShowSpawn(false)} onSpawned={() => { setShowSpawn(false); refresh(); }} />}
    </>
  );
}

function SpawnModal({ skills, onClose, onSpawned }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [tools, setTools] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const toggle = (id) => setTools((prev) => prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]);

  const submit = async () => {
    setBusy(true);
    try {
      const r = await apiFetch('/api/agents/spawn', {
        method: 'POST',
        body: JSON.stringify({
          name,
          description,
          system_prompt: systemPrompt,
          tool_permissions: tools,
        }),
      });
      if (!r.ok) setError(`${r.status} ${await r.text()}`);
      else onSpawned();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Spawn a specialist"
      size="lg"
      actions={(
        <>
          <button type="button" className="v2-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="v2-btn v2-btn--primary" onClick={submit} disabled={busy || !name.trim()}>
            {busy ? 'Spawning…' : 'Spawn'}
          </button>
        </>
      )}
    >
      <label className="v2-step-field">
        <span>Name</span>
        <input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="v2-step-field">
        <span>Description</span>
        <input className="v2-input" value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="v2-step-field">
        <span>System prompt</span>
        <textarea className="v2-code-editor" rows={6} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} />
      </label>
      <div className="v2-p v2-p--muted" style={{ marginTop: 12 }}>Tool permissions</div>
      <div className="v2-skill-card-phrases">
        {skills.map((s) => {
          const id = s.skill_id || s.id;
          return (
            <button
              key={id}
              type="button"
              className={`v2-chip${tools.includes(id) ? ' v2-chip--live' : ' v2-chip--muted'}`}
              onClick={() => toggle(id)}
            >
              {id}
            </button>
          );
        })}
      </div>
      {error && <div className="v2-chip v2-chip--error" style={{ marginTop: 12 }}>{error}</div>}
    </Modal>
  );
}

function ProposalsTab() {
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiJson('/api/agents/proposals')
      .then((d) => setProposals(d.proposals || d || []))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Pane title={`Proposals (${proposals.length})`}>
      {loading && <EmptyState title="Loading…" />}
      {!loading && proposals.length === 0 && <EmptyState title="No recurring patterns yet" hint="Mitosis watches your recent turns for 5+ uses of the same tool set." />}
      <ul className="v2-mem-list">
        {proposals.map((p, i) => (
          <li key={p.pattern_id || i}>
            <Glass level={0} radius="md" padding="md">
              <div className="v2-mem-content">{p.topic_cluster || p.pattern_id}</div>
              <div className="v2-mem-meta">
                {p.occurrence_count != null && <span>seen {p.occurrence_count}×</span>}
                {Array.isArray(p.tool_affinities) && <span>· tools: {p.tool_affinities.slice(0, 5).join(', ')}</span>}
              </div>
            </Glass>
          </li>
        ))}
      </ul>
    </Pane>
  );
}

function StatsTab() {
  const [stats, setStats] = useState(null);
  useEffect(() => { apiJson('/api/agents/stats').then(setStats).catch(() => setStats({})); }, []);
  if (!stats) return <Pane title="Stats"><EmptyState title="Loading…" /></Pane>;
  return (
    <Pane title="Mitosis stats">
      <div className="v2-grid v2-grid--stats">
        {Object.entries(stats).map(([k, v]) => (
          <Glass key={k} level={1} radius="md" padding="md">
            <div className="v2-stat-label">{k.replace(/_/g, ' ')}</div>
            <div className="v2-stat-value">{typeof v === 'number' ? v : JSON.stringify(v)}</div>
          </Glass>
        ))}
      </div>
    </Pane>
  );
}
