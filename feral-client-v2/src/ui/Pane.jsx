import React from 'react';
import Glass from './Glass';

/**
 * Pane — a focused, translucent panel for detail surfaces. Used for
 * chat wiki/threads/snapshots, forge drafts, devices detail, and
 * third-party GenUI apps.
 *
 * ``leading`` renders before the title (e.g. a `<BackButton />` on a
 * deep route like /oversight). ``actions`` stays right-aligned.
 */
export default function Pane({ title, leading, actions, children, className = '', padding = 'lg' }) {
  return (
    <Glass
      as="section"
      level={2}
      radius="lg"
      padding={padding}
      className={`v2-pane ${className}`.trim()}
    >
      {(title || leading || actions) && (
        <header className="v2-pane-header">
          {leading && <div className="v2-pane-leading">{leading}</div>}
          {title && <h2 className="v2-pane-title">{title}</h2>}
          {actions && <div className="v2-pane-actions">{actions}</div>}
        </header>
      )}
      <div className="v2-pane-body">{children}</div>
    </Glass>
  );
}
