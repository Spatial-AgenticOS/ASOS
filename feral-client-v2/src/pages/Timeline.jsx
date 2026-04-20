import React, { useEffect, useState } from 'react';
import Pane from '../ui/Pane';
import Glass from '../ui/Glass';
import { apiJson } from '../lib/api';

export default function Timeline() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await apiJson('/api/timeline');
        if (!cancelled) setItems(d.timeline || d.items || []);
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="v2-page v2-page--stack" data-testid="v2-marker">
      <Pane title="Timeline">
        {loading && <div className="v2-empty">Loading…</div>}
        {!loading && items.length === 0 && (
          <div className="v2-empty">No events yet. Your day will show up here.</div>
        )}
        <ul className="v2-timeline">
          {items.map((item, idx) => (
            <li key={item.id || idx} className="v2-timeline-row">
              <Glass level={0} radius="sm" padding="sm">
                <div className="v2-timeline-time">{item.time || item.timestamp || ''}</div>
                <div className="v2-timeline-text">{item.text || item.title || JSON.stringify(item).slice(0, 120)}</div>
              </Glass>
            </li>
          ))}
        </ul>
      </Pane>
    </div>
  );
}
