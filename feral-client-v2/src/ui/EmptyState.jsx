import React from 'react';

/**
 * EmptyState — consistent "nothing here yet" with optional action button.
 */
export default function EmptyState({ icon, title, hint, action }) {
  return (
    <div className="v2-empty-state">
      {icon && <div className="v2-empty-state-icon" aria-hidden="true">{icon}</div>}
      <div className="v2-empty-state-title">{title}</div>
      {hint && <div className="v2-empty-state-hint">{hint}</div>}
      {action && <div className="v2-empty-state-action">{action}</div>}
    </div>
  );
}
