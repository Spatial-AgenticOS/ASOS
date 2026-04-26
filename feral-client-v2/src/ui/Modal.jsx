import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import Glass from './Glass';

/**
 * Modal — translucent overlay sheet. Closes on ESC or backdrop click
 * (unless ``dismissible`` is false). Never uses inline styles.
 *
 * Mount strategy. The modal renders via React Portal onto document.body
 * so it is NOT a descendant of .v2-shell-main. .v2-shell-main creates
 * its own stacking context (positive z-index above .v2-ambient), which
 * historically trapped the modal below the dock + menubar even though
 * its CSS z-index value was higher. The portal puts the backdrop in
 * the body's stacking context where the named `--z-modal` constant
 * (see styles/_z.css) places it cleanly above the dock (--z-dock).
 *
 * Roadmap §A.2: this fixes the user-reported "click 'Pair a device' →
 * row appears in the historical list but the modal never becomes
 * visible" bug by making the modal actually paint on top.
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
  if (typeof document === 'undefined') return null;

  const node = (
    <div
      className="v2-modal-backdrop"
      role="presentation"
      data-testid="v2-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget && dismissible) onClose?.();
      }}
    >
      <Glass
        as="div"
        level="elev"
        radius="lg"
        padding="none"
        className={`v2-modal v2-modal-card v2-modal--${size}`}
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

  return createPortal(node, document.body);
}
