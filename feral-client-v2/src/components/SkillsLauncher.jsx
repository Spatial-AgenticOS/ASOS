import React, { useEffect, useMemo, useState } from 'react';
import { Search, X, Pin, PinOff, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import Glass from '../ui/Glass';
import { apiFetch } from '../lib/api';

/**
 * SkillsLauncher — full-surface popup showing every loaded skill.
 *
 *   - Search across name / skill_id / description
 *   - Click a row to expand description, trigger phrases, endpoint count
 *   - Pin / unpin — writes to ``localStorage.feral_pinned_skills`` so the
 *     Home page's compact strip is user-editable
 *   - Hot-reload a skill via POST /api/skills/reload
 */

export const PIN_STORAGE_KEY = 'feral_pinned_skills';
export const DEFAULT_PINNED = [
  'coding_tools', 'web_search', 'calendar_google', 'messaging_channels',
  'smart_home_hue', 'notes_memory', 'weather_current', 'self_introspection',
];
export const MAX_PINNED = 8;

export function readPinned() {
  if (typeof localStorage === 'undefined') return DEFAULT_PINNED;
  try {
    const raw = localStorage.getItem(PIN_STORAGE_KEY);
    if (!raw) return DEFAULT_PINNED;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((s) => typeof s === 'string')) {
      return parsed.slice(0, MAX_PINNED);
    }
  } catch { /* fall through */ }
  return DEFAULT_PINNED;
}

export function writePinned(list) {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify(list.slice(0, MAX_PINNED)));
    window.dispatchEvent(new CustomEvent('feral_pinned_change'));
  } catch { /* silent */ }
}

export default function SkillsLauncher({ open, onClose, skills = [] }) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [pinned, setPinned] = useState(readPinned());
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    if (!open) { setQuery(''); setExpanded(null); return undefined; }
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter((s) => {
      const id = (s.skill_id || s.id || '').toLowerCase();
      const name = (s.name || '').toLowerCase();
      const desc = (s.description || '').toLowerCase();
      return id.includes(q) || name.includes(q) || desc.includes(q);
    });
  }, [skills, query]);

  const togglePin = (id) => {
    setPinned((prev) => {
      const next = prev.includes(id)
        ? prev.filter((x) => x !== id)
        : [id, ...prev.filter((x) => x !== id)].slice(0, MAX_PINNED);
      writePinned(next);
      return next;
    });
  };

  const reload = async (id) => {
    setBusy(id);
    try {
      await apiFetch(`/api/skills/reload?skill_id=${encodeURIComponent(id)}`, { method: 'POST' });
    } finally { setBusy(null); }
  };

  if (!open) return null;

  return (
    <div
      className="v2-skills-launcher-backdrop"
      role="presentation"
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
    >
      <Glass
        as="section"
        level="elev"
        radius="lg"
        padding="none"
        className="v2-skills-launcher"
        role="dialog"
        aria-label="All skills"
        aria-modal="true"
      >
        <header className="v2-skills-launcher-head">
          <Search size={15} aria-hidden="true" />
          <input
            className="v2-hub-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${skills.length} skill${skills.length === 1 ? '' : 's'}…`}
            aria-label="Search skills"
            autoFocus
          />
          <span className="v2-chip v2-chip--muted">{pinned.length}/{MAX_PINNED} pinned</span>
          <button
            type="button"
            className="v2-btn v2-btn--ghost"
            onClick={() => onClose?.()}
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </header>

        <div className="v2-skills-launcher-body">
          {list.length === 0 && <div className="v2-p v2-p--muted">No matches.</div>}
          <ul className="v2-skills-launcher-list">
            {list.map((s) => {
              const id = s.skill_id || s.id;
              const isPinned = pinned.includes(id);
              const isExpanded = expanded === id;
              return (
                <li key={id} className={`v2-skill-row${isExpanded ? ' is-expanded' : ''}`}>
                  <button
                    type="button"
                    className="v2-skill-row-head"
                    onClick={() => setExpanded((prev) => (prev === id ? null : id))}
                  >
                    <span className="v2-skill-row-name">{s.name || id}</span>
                    <code className="v2-skill-row-id">{id}</code>
                    <span className="v2-skill-row-chevron" aria-hidden="true">
                      {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    </span>
                  </button>
                  <div className="v2-skill-row-actions">
                    <button
                      type="button"
                      className={`v2-btn v2-btn--ghost${isPinned ? ' is-on' : ''}`}
                      onClick={() => togglePin(id)}
                      aria-label={isPinned ? 'Unpin' : 'Pin'}
                      title={isPinned ? 'Unpin from Home' : 'Pin to Home'}
                    >
                      {isPinned ? <Pin size={13} /> : <PinOff size={13} />}
                    </button>
                    <button
                      type="button"
                      className="v2-btn v2-btn--ghost"
                      onClick={() => reload(id)}
                      disabled={busy === id}
                      aria-label="Hot-reload skill"
                      title="Hot-reload"
                    >
                      <RefreshCw size={13} />
                    </button>
                  </div>
                  {isExpanded && (
                    <div className="v2-skill-row-detail">
                      {s.description && <p className="v2-p">{s.description}</p>}
                      {Array.isArray(s.trigger_phrases) && s.trigger_phrases.length > 0 && (
                        <div className="v2-skill-card-phrases">
                          {s.trigger_phrases.slice(0, 6).map((p, i) => (
                            <span key={i} className="v2-chip v2-chip--muted">"{p}"</span>
                          ))}
                        </div>
                      )}
                      <div className="v2-skill-card-meta">
                        {s.version && <span className="v2-chip">v{s.version}</span>}
                        {Array.isArray(s.endpoints) && (
                          <span className="v2-chip">{s.endpoints.length} endpoints</span>
                        )}
                        {s.approval_mode && (
                          <span className={`v2-chip v2-chip--${s.approval_mode}`}>{s.approval_mode}</span>
                        )}
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </Glass>
    </div>
  );
}
