import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Play, Wrench } from 'lucide-react';
import { Link } from 'react-router-dom';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import EmptyState from '../ui/EmptyState';
import { apiJson, apiFetch } from '../lib/api';

/**
 * Skills — shows every loaded skill. Reload button per skill.
 * Pending drafts banner links to Forge.
 */
export default function Skills() {
  const [skills, setSkills] = useState([]);
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(null);
  const [filter, setFilter] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.allSettled([
        apiJson('/skills'),
        apiJson('/api/skills/pending'),
      ]);
      if (s.status === 'fulfilled') setSkills(s.value?.skills || s.value || []);
      if (p.status === 'fulfilled') setPending(p.value?.pending || p.value || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const reload = async (id) => {
    setReloading(id);
    try {
      await apiFetch(`/api/skills/reload?skill_id=${encodeURIComponent(id)}`, { method: 'POST' });
      await refresh();
    } finally {
      setReloading(null);
    }
  };

  const visible = skills.filter((s) => {
    if (!filter) return true;
    const q = filter.toLowerCase();
    return (
      (s.skill_id || '').toLowerCase().includes(q) ||
      (s.name || '').toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q)
    );
  });

  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane
        title={`Skills (${skills.length})`}
        actions={(
          <>
            <input
              type="search"
              className="v2-input"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter…"
              style={{ minWidth: 160 }}
            />
            <button type="button" className="v2-btn v2-btn--ghost" onClick={refresh} aria-label="Refresh"><RefreshCw size={13} /></button>
          </>
        )}
      >
        {pending.length > 0 && (
          <Glass level={1} radius="md" padding="md" className="v2-dash-alert">
            <Wrench size={14} aria-hidden="true" />
            <div>
              <div className="v2-dash-alert-title">{pending.length} draft skill{pending.length > 1 ? 's' : ''} pending approval</div>
              <div className="v2-dash-alert-msg">Tool Genesis proposed new capabilities from recent requests.</div>
            </div>
            <Link to="/forge" className="v2-btn v2-btn--primary">Open Forge</Link>
          </Glass>
        )}

        {loading && <EmptyState title="Loading skills…" />}
        {!loading && skills.length === 0 && <EmptyState title="No skills loaded" hint="Check the Brain boot log." />}

        <div className="v2-skills-grid">
          {visible.map((s) => {
            const id = s.skill_id || s.id;
            return (
              <Glass key={id} level={0} radius="md" padding="md" className="v2-skill-card">
                <header className="v2-skill-card-head">
                  <h3 className="v2-skill-card-name">{s.name || id}</h3>
                  <code className="v2-skill-card-id">{id}</code>
                </header>
                {s.description && <p className="v2-p v2-p--muted">{s.description}</p>}
                <div className="v2-skill-card-meta">
                  {s.version && <span className="v2-chip">v{s.version}</span>}
                  {s.approval_mode && <span className={`v2-chip v2-chip--${s.approval_mode}`}>{s.approval_mode}</span>}
                  {Array.isArray(s.endpoints) && s.endpoints.length > 0 && (
                    <span className="v2-chip">{s.endpoints.length} endpoints</span>
                  )}
                </div>
                {Array.isArray(s.trigger_phrases) && s.trigger_phrases.length > 0 && (
                  <div className="v2-skill-card-phrases">
                    {s.trigger_phrases.slice(0, 4).map((p, i) => (
                      <span key={i} className="v2-chip v2-chip--muted">"{p}"</span>
                    ))}
                  </div>
                )}
                <div className="v2-forge-actions">
                  <button
                    type="button"
                    className="v2-btn"
                    onClick={() => reload(id)}
                    disabled={reloading === id}
                  >
                    <RefreshCw size={12} /> {reloading === id ? 'Reloading…' : 'Hot-reload'}
                  </button>
                </div>
              </Glass>
            );
          })}
        </div>
      </Pane>
    </div>
  );
}
