import React from 'react';

/**
 * Tabs — segmented control. Controlled: caller owns ``value`` + ``onChange``.
 * Each item is { id, label, count? }.
 */
export default function Tabs({ items, value, onChange, size = 'md' }) {
  return (
    <div
      className={`v2-tabs v2-tabs--${size}`}
      role="tablist"
      aria-label="Tab strip"
    >
      {items.map((item) => {
        const isActive = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`v2-tab${isActive ? ' is-active' : ''}`}
            onClick={() => onChange(item.id)}
          >
            <span className="v2-tab-label">{item.label}</span>
            {typeof item.count === 'number' && (
              <span className="v2-tab-count">{item.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
