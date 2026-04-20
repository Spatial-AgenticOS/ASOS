import React from 'react';

/**
 * Glass — the foundational translucent panel. Every v2 container uses this
 * primitive so blur, hairline, and radius stay consistent.
 */
export default function Glass({
  as: Tag = 'div',
  level = 1,
  radius = 'md',
  padding = 'md',
  className = '',
  children,
  ...rest
}) {
  const cls = [
    'v2-glass',
    `v2-glass--level-${level}`,
    `v2-glass--radius-${radius}`,
    `v2-glass--pad-${padding}`,
    className,
  ].filter(Boolean).join(' ');
  return (
    <Tag className={cls} {...rest}>
      {children}
    </Tag>
  );
}
