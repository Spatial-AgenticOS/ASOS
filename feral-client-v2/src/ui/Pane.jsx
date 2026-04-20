import React from 'react';
import Glass from './Glass';

/**
 * Pane — a focused, translucent panel for detail surfaces. Used for
 * chat wiki/threads/snapshots, forge drafts, devices detail, and
 * third-party GenUI apps.
 */
export default function Pane({ title, actions, children, className = '', padding = 'lg' }) {
  return (
    <Glass
      as="section"
      level={2}
      radius="lg"
      padding={padding}
      className={`v2-pane ${className}`.trim()}
    >
      {(title || actions) && (
        <header className="v2-pane-header">
          {title && <h2 className="v2-pane-title">{title}</h2>}
          {actions && <div className="v2-pane-actions">{actions}</div>}
        </header>
      )}
      <div className="v2-pane-body">{children}</div>
    </Glass>
  );
}
