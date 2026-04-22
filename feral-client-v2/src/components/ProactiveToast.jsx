/**
 * ProactiveToast — floating bottom-right card that picks up
 * `proactive_alert` events from the brain and renders either:
 *   (a) a simple title/body pair (legacy path), OR
 *   (b) the full SDUI tree if the brain attached `sdui` to the payload.
 *
 * One toast is shown at a time; newer proactive alerts replace older.
 * The user dismisses by clicking the X or interacting with an action
 * button inside the SDUI tree. Dismissal POSTs `/api/proactive/dismiss`
 * so the ProactiveEngine records the outcome for future weighting.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import Glass from '../ui/Glass';
import SduiRenderer from '../ui/SduiRenderer';
import { useFeralSocket, sendUiEvent } from '../hooks/useFeralSocket';
import { apiFetch } from '../lib/api';

export default function ProactiveToast() {
  const socket = useFeralSocket();
  const [alert, setAlert] = useState(null);

  useEffect(() => {
    const unsub = socket.subscribe((msg) => {
      if (!msg || typeof msg !== 'object') return;
      const type = msg.type;
      const event = msg.event;
      const data = msg.data || msg.payload;
      if (!(type === 'state_push' && event === 'proactive_alert') && type !== 'proactive_alert') return;
      if (!data) return;
      setAlert({
        trigger_id: data.trigger_id || '',
        title: data.title || 'Heads up',
        body: data.body || data.message || '',
        priority: (data.priority || 'NORMAL').toLowerCase(),
        action: data.action || '',
        action_payload: data.action_payload || {},
        sdui: data.sdui || null,
      });
    });
    return unsub;
  }, [socket]);

  const dismiss = useCallback(async () => {
    if (!alert) return;
    const triggerId = alert.trigger_id;
    setAlert(null);
    if (triggerId) {
      try {
        await apiFetch('/api/proactive/dismiss', {
          method: 'POST',
          body: JSON.stringify({ trigger_id: triggerId }),
        });
      } catch {
        /* best-effort */
      }
    }
  }, [alert]);

  if (!alert) return null;

  return (
    <div
      className="v2-proactive-toast"
      role="status"
      aria-live="polite"
      data-testid="proactive-toast"
      style={{
        position: 'fixed',
        right: 20, bottom: 130,
        maxWidth: 420, minWidth: 260,
        zIndex: 60,
      }}
    >
      <Glass level={2} radius="md" padding="md">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <strong style={{ fontSize: 13 }}>{alert.title}</strong>
          <button type="button" className="v2-btn v2-btn--ghost" onClick={dismiss} aria-label="Dismiss">
            <X size={13} />
          </button>
        </div>
        {alert.sdui ? (
          <SduiRenderer
            tree={alert.sdui}
            onAction={(action_id, value) => {
              sendUiEvent(socket, {
                screen_id: `proactive:${alert.trigger_id}`,
                action_id,
                value,
              });
              setAlert(null);
            }}
          />
        ) : (
          <div style={{ fontSize: 12, opacity: 0.85, lineHeight: 1.45 }}>{alert.body}</div>
        )}
      </Glass>
    </div>
  );
}
