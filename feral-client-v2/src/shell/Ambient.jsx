import React, { useEffect, useRef, useState } from 'react';
import Orb from '../ui/Orb';
import LiveOpsStream from './LiveOpsStream';
import { useSomatic } from '../hooks/useSomatic';

/**
 * Ambient — hybrid background.
 *
 *   persona  ⇄  liveops
 *
 * Persona is the default resting state: large blurred Orb + a subtle
 * somatic-driven hue. Live-ops is the opt-in diagnostic state: a faint
 * stream of Brain events behind everything.
 *
 * Expand triggers: hover bottom-third, press Cmd-Period, or dispatch the
 * custom `v2:ambient-expand` event. Collapses after 3 s idle.
 */
const COLLAPSE_MS = 3000;

export default function Ambient() {
  const [expanded, setExpanded] = useState(false);
  const somatic = useSomatic();
  const timerRef = useRef(null);

  useEffect(() => {
    const armCollapse = () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setExpanded(false), COLLAPSE_MS);
    };

    const expand = () => {
      setExpanded(true);
      armCollapse();
    };

    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.code === 'Period') {
        e.preventDefault();
        setExpanded((prev) => !prev);
        armCollapse();
      }
    };
    const onPointer = (e) => {
      const y = e.clientY;
      const h = window.innerHeight || 1;
      if (y / h > 0.72) expand();
    };
    const onCustom = () => expand();

    window.addEventListener('keydown', onKey);
    window.addEventListener('pointermove', onPointer, { passive: true });
    window.addEventListener('v2:ambient-expand', onCustom);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pointermove', onPointer);
      window.removeEventListener('v2:ambient-expand', onCustom);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const hue = somatic.cognitiveLoad > 0.7
    ? 'warm'
    : somatic.cognitiveLoad > 0.4
      ? 'neutral'
      : 'cool';

  return (
    <div
      className={`v2-ambient v2-ambient--${hue}${expanded ? ' is-expanded' : ''}`}
      aria-hidden="true"
    >
      <div className="v2-ambient-persona">
        <Orb size={420} mode={somatic.orbMode} />
      </div>
      <div className="v2-ambient-ops">
        <LiveOpsStream active={expanded} />
      </div>
    </div>
  );
}
