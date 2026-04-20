import React from 'react';
import { Trash2, GripVertical } from 'lucide-react';
import Glass from '../ui/Glass';

/**
 * StepBuilder — typed editor for TaskFlow / Routine steps.
 * Each step type has its own form. Steps are passed up as a list of
 * plain-object dicts in the exact shape the Brain's TaskFlow runtime
 * expects (see feral-core/agents/taskflow.py).
 *
 * Usage:
 *   <StepBuilder steps={steps} onChange={setSteps} skills={skills} />
 */

export const STEP_TYPES = [
  { id: 'noop', label: 'Noop (placeholder)' },
  { id: 'sleep', label: 'Sleep (pause N seconds)' },
  { id: 'note.save', label: 'Save note to memory' },
  { id: 'memory.search', label: 'Search semantic memory' },
  { id: 'http.get', label: 'HTTP GET' },
  { id: 'skill.invoke', label: 'Invoke a skill endpoint' },
  { id: 'llm.chat', label: 'LLM prompt' },
  { id: 'wiki.compile', label: 'Compile / refresh wiki' },
  { id: 'condition', label: 'Conditional branch' },
];

function StepFields({ step, onChange, skills }) {
  const patch = (update) => onChange({ ...step, ...update });

  switch (step.type) {
    case 'sleep':
      return (
        <label className="v2-step-field">
          <span>Seconds</span>
          <input
            type="number"
            className="v2-input"
            value={step.seconds ?? 5}
            min={0}
            onChange={(e) => patch({ seconds: Number(e.target.value) })}
          />
        </label>
      );
    case 'note.save':
      return (
        <>
          <label className="v2-step-field">
            <span>Content</span>
            <textarea
              className="v2-code-editor"
              rows={3}
              value={step.content ?? ''}
              onChange={(e) => patch({ content: e.target.value })}
            />
          </label>
          <label className="v2-step-field">
            <span>Tags (comma-separated)</span>
            <input
              className="v2-input"
              value={(step.tags || []).join(', ')}
              onChange={(e) => patch({ tags: e.target.value.split(',').map((t) => t.trim()).filter(Boolean) })}
            />
          </label>
        </>
      );
    case 'memory.search':
      return (
        <label className="v2-step-field">
          <span>Query</span>
          <input
            className="v2-input"
            value={step.q ?? ''}
            onChange={(e) => patch({ q: e.target.value })}
          />
        </label>
      );
    case 'http.get':
      return (
        <label className="v2-step-field">
          <span>URL</span>
          <input
            type="url"
            className="v2-input"
            value={step.url ?? ''}
            onChange={(e) => patch({ url: e.target.value })}
            placeholder="https://…"
          />
        </label>
      );
    case 'skill.invoke':
      return (
        <>
          <label className="v2-step-field">
            <span>Skill</span>
            <select
              className="v2-select"
              value={step.skill_id ?? ''}
              onChange={(e) => patch({ skill_id: e.target.value })}
            >
              <option value="">-- pick a skill --</option>
              {skills.map((s) => (
                <option key={s.skill_id || s.id} value={s.skill_id || s.id}>
                  {s.name || s.skill_id || s.id}
                </option>
              ))}
            </select>
          </label>
          <label className="v2-step-field">
            <span>Endpoint</span>
            <input
              className="v2-input"
              value={step.endpoint ?? ''}
              placeholder="list_today, send, …"
              onChange={(e) => patch({ endpoint: e.target.value })}
            />
          </label>
          <label className="v2-step-field">
            <span>Args (JSON)</span>
            <textarea
              className="v2-code-editor"
              rows={3}
              value={typeof step.args === 'string' ? step.args : JSON.stringify(step.args || {}, null, 2)}
              onChange={(e) => {
                try {
                  patch({ args: JSON.parse(e.target.value) });
                } catch {
                  patch({ args: e.target.value });
                }
              }}
            />
          </label>
        </>
      );
    case 'llm.chat':
      return (
        <label className="v2-step-field">
          <span>Prompt template</span>
          <textarea
            className="v2-code-editor"
            rows={4}
            value={step.prompt_template ?? ''}
            onChange={(e) => patch({ prompt_template: e.target.value })}
            placeholder="Use {{ previous_output }} to reference the last step's result"
          />
        </label>
      );
    case 'wiki.compile':
      return (
        <label className="v2-step-field">
          <span>Page (optional)</span>
          <input
            className="v2-input"
            value={step.page ?? ''}
            onChange={(e) => patch({ page: e.target.value })}
            placeholder="Leave empty to rebuild everything"
          />
        </label>
      );
    case 'condition':
      return (
        <>
          <label className="v2-step-field">
            <span>Expression</span>
            <input
              className="v2-input"
              value={step.expression ?? ''}
              onChange={(e) => patch({ expression: e.target.value })}
              placeholder="previous_output.length > 0"
            />
          </label>
          <label className="v2-step-field">
            <span>On true — skip to step #</span>
            <input
              type="number"
              className="v2-input"
              value={step.goto_step ?? ''}
              onChange={(e) => patch({ goto_step: Number(e.target.value) || null })}
            />
          </label>
        </>
      );
    case 'noop':
    default:
      return <div className="v2-p v2-p--muted">No parameters.</div>;
  }
}

export default function StepBuilder({ steps, onChange, skills = [] }) {
  const update = (i, next) => {
    const copy = [...steps];
    copy[i] = next;
    onChange(copy);
  };
  const remove = (i) => {
    const copy = [...steps];
    copy.splice(i, 1);
    onChange(copy);
  };
  const add = () => onChange([...steps, { type: 'noop' }]);
  const move = (i, dir) => {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    const copy = [...steps];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };

  return (
    <div className="v2-step-builder">
      {steps.map((step, i) => (
        <Glass key={i} level={0} radius="md" padding="md" className="v2-step-card">
          <header className="v2-step-head">
            <div className="v2-step-ord">
              <button type="button" className="v2-btn v2-btn--ghost" onClick={() => move(i, -1)} aria-label="Move up" disabled={i === 0}>↑</button>
              <button type="button" className="v2-btn v2-btn--ghost" onClick={() => move(i, 1)} aria-label="Move down" disabled={i === steps.length - 1}>↓</button>
              <GripVertical size={12} aria-hidden="true" />
              <span className="v2-step-num">#{i + 1}</span>
            </div>
            <select
              className="v2-select v2-step-type"
              value={step.type}
              onChange={(e) => update(i, { ...step, type: e.target.value })}
            >
              {STEP_TYPES.map((t) => (
                <option key={t.id} value={t.id}>{t.label}</option>
              ))}
            </select>
            <button type="button" className="v2-btn v2-btn--ghost" onClick={() => remove(i)} aria-label="Delete step">
              <Trash2 size={14} />
            </button>
          </header>
          <div className="v2-step-body">
            <StepFields step={step} onChange={(next) => update(i, next)} skills={skills} />
          </div>
        </Glass>
      ))}
      <button type="button" className="v2-btn" onClick={add}>+ Add step</button>
    </div>
  );
}
