import { useEffect, useState } from 'react';
import { apiJson } from '../lib/api';

const POLL_MS = 10000;

function orbModeFor(cognitiveLoad) {
  if (cognitiveLoad > 0.7) return 'alerting';
  if (cognitiveLoad > 0.4) return 'thinking';
  return 'idle';
}

/**
 * useSomatic — periodically polls /api/dashboard for the somatic block and
 * derives the Orb mode + cognitive load. Falls back to a neutral idle state
 * if the Brain doesn't expose somatic data.
 */
export function useSomatic() {
  const [state, setState] = useState({
    cognitiveLoad: 0,
    heartRate: 0,
    orbMode: 'idle',
  });

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const data = await apiJson('/api/dashboard');
        if (cancelled) return;
        const s = data?.somatic || {};
        const load = Number(s.cognitive_load || 0);
        const hr = Number(s.heart_rate || 0);
        setState({
          cognitiveLoad: Number.isFinite(load) ? load : 0,
          heartRate: Number.isFinite(hr) ? hr : 0,
          orbMode: orbModeFor(load),
        });
      } catch {
        // Silent — ambient surfaces its own visible banner on disconnect.
      }
    };

    tick();
    const interval = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return state;
}
