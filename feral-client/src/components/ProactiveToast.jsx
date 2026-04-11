import React, { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, Bell, Lightbulb, Calendar, X, ChevronRight } from 'lucide-react';

const ICON_MAP = {
  warning:  AlertTriangle,
  reminder: Calendar,
  suggestion: Lightbulb,
};

export default function ProactiveToast({ alert, onDismiss, onAction }) {
  const [visible, setVisible] = useState(false);
  const [exiting, setExiting] = useState(false);

  const dismiss = useCallback(() => {
    setExiting(true);
    setTimeout(() => {
      setVisible(false);
      setExiting(false);
      if (onDismiss) onDismiss();
    }, 400);
  }, [onDismiss]);

  useEffect(() => {
    if (!alert) {
      setVisible(false);
      return;
    }
    setExiting(false);
    setVisible(true);
    const timer = setTimeout(dismiss, 8000);
    return () => clearTimeout(timer);
  }, [alert, dismiss]);

  if (!visible || !alert) return null;

  const kind = alert.kind || 'info';
  const Icon = ICON_MAP[kind] || Bell;
  const borderColor =
    kind === 'warning'    ? 'border-amber-500/30' :
    kind === 'suggestion' ? 'border-feral-accent/30' :
    kind === 'reminder'   ? 'border-feral-accent/30' :
    'border-feral-border';
  const iconColor =
    kind === 'warning'    ? 'text-amber-400' :
    kind === 'suggestion' ? 'text-feral-accent' :
    kind === 'reminder'   ? 'text-feral-accent' :
    'text-feral-text-secondary';

  return (
    <div
      className={`proactive-toast fixed top-4 right-4 z-50 max-w-sm w-full pointer-events-auto
        bg-feral-surface/95 backdrop-blur-xl border ${borderColor} rounded-xl shadow-2xl shadow-black/30
        ${exiting ? 'proactive-toast-exit' : 'proactive-toast-enter'}`}
    >
      <div className="flex items-start gap-3 p-4">
        <div className={`mt-0.5 flex-shrink-0 ${iconColor}`}>
          <Icon size={18} />
        </div>
        <div className="flex-1 min-w-0">
          {alert.title && (
            <div className="text-sm font-semibold text-feral-text mb-0.5">{alert.title}</div>
          )}
          <div className="text-[12px] text-feral-text-secondary leading-relaxed">
            {alert.message}
          </div>
          {alert.action_label && (
            <button
              onClick={() => { if (onAction) onAction(alert); dismiss(); }}
              className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-feral-accent hover:text-feral-accent/80 transition"
            >
              {alert.action_label}
              <ChevronRight size={12} />
            </button>
          )}
        </div>
        <button
          onClick={dismiss}
          className="flex-shrink-0 p-1 rounded-lg text-feral-text-muted hover:text-feral-text hover:bg-feral-card-hover transition"
        >
          <X size={14} />
        </button>
      </div>
      <div className="h-0.5 mx-4 mb-2 rounded-full bg-feral-border overflow-hidden">
        <div
          className={`h-full rounded-full ${
            kind === 'warning' ? 'bg-amber-400' : 'bg-feral-accent'
          } ${exiting ? '' : 'proactive-toast-progress'}`}
        />
      </div>
    </div>
  );
}
