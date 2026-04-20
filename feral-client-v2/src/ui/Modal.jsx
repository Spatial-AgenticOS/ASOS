import React, { useEffect } from 'react';
import Glass from './Glass';

/**
 * Modal — translucent overlay sheet. Closes on ESC or backdrop click
 * (unless ``dismissible`` is false). Never uses inline styles.
 */
export default function Modal({
  open,
  onClose,
  title,
  children,
  actions,
  dismissible = true,
  size = 'md',
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape' && dismissible) onClose?.();
    };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, dismissible, onClose]);

  if (!open) return null;

  return (
    <div
      className="v2-modal-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget && dismissible) onClose?.();
      }}
    >
      <Glass
        as="div"
        level="elev"
        radius="lg"
        padding="none"
        className={`v2-modal v2-modal--${size}`}
        role="dialog"
        aria-modal="true"
        aria-label={title || 'Dialog'}
      >
        {title && (
          <header className="v2-modal-header">
            <h2 className="v2-modal-title">{title}</h2>
            {dismissible && (
              <button
                type="button"
                className="v2-btn v2-btn--ghost v2-modal-close"
                onClick={() => onClose?.()}
                aria-label="Close"
              >
                ×
              </button>
            )}
          </header>
        )}
        <div className="v2-modal-body">{children}</div>
        {actions && <footer className="v2-modal-footer">{actions}</footer>}
      </Glass>
    </div>
  );
}
