import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';

/**
 * BackButton — canonical "drilled-into a deep route" exit affordance.
 *
 * Routes like /oversight and /memory/context are reached from page-action
 * links inside other panes (Glass Brain, Memory). Browser back works,
 * but in-app users expect a header chevron. This is that chevron.
 *
 * Behaviour:
 *   - useNavigate(-1) when there is in-app history to go back to.
 *   - Falls back to ``fallback`` (default /glass-brain) when the page
 *     was deep-linked open with no history (router idx === 0 OR the
 *     location key is "default").
 *
 * Lives in ui/ so every deep page can drop in `<BackButton />` without
 * pulling in router boilerplate.
 */
export default function BackButton({ fallback = '/glass-brain', label = 'Back' }) {
  const navigate = useNavigate();
  const location = useLocation();

  const onClick = () => {
    // location.key === 'default' means the user landed here directly
    // (deep-link, refresh on this route, opening a new tab to it). In
    // that case there is no in-app prior route to fall back to.
    const hasHistory = location.key && location.key !== 'default';
    if (hasHistory) {
      navigate(-1);
    } else {
      navigate(fallback);
    }
  };

  return (
    <button
      type="button"
      className="v2-btn v2-btn--ghost v2-back-btn"
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      <ChevronLeft size={13} aria-hidden="true" /> {label}
    </button>
  );
}
