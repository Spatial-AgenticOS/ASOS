import React from 'react';

/**
 * CodeEditor — minimal monospaced textarea used by Identity + TaskFlow
 * step builder + Policy editor. No syntax highlighting (we'd pull in
 * highlight.js which is heavy); the Brain's data is short enough that
 * a styled textarea is fine.
 */
export default function CodeEditor({
  value,
  onChange,
  placeholder,
  readOnly,
  language = 'text',
  rows = 14,
  'aria-label': ariaLabel,
}) {
  return (
    <textarea
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
      placeholder={placeholder}
      readOnly={readOnly}
      rows={rows}
      spellCheck={false}
      aria-label={ariaLabel || `Editor (${language})`}
      className={`v2-code-editor v2-code-editor--${language}`}
    />
  );
}
