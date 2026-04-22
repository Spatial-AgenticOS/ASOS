import { describe, it, expect } from 'vitest';
import { renderV2 } from '../_helpers/renderV2';
import ForYouToday from '../../components/ForYouToday';

describe('ForYouToday', () => {
  it('renders an empty state when the brain has no ideas', async () => {
    const rendered = renderV2(<ForYouToday />, {
      fetch: (url) => {
        if (url.includes('/api/ideas/today')) return { ideas: [], count: 0 };
        return {};
      },
    });
    expect(await rendered.findByText(/Nothing to suggest yet/i)).toBeInTheDocument();
  });

  it('renders idea rows with accept + dismiss buttons', async () => {
    const ideas = [
      {
        id: 'i1',
        kind: 'health',
        text: 'Your HRV dropped 18% this week. Want a 5-min breathing session?',
        source_signals: ['baseline:hrv:anomaly:below'],
        action: { kind: 'route', route: '/health', verb: 'view_health' },
        severity: 'warning',
      },
      {
        id: 'i2',
        kind: 'work',
        text: 'You paused "ship v2026.4.23" 6h ago. Resume?',
        source_signals: ['consciousness:intent:x'],
        action: { kind: 'resume_consciousness', route: '/', verb: 'resume', payload: { consciousness_id: 'x' } },
        severity: 'info',
      },
    ];
    const rendered = renderV2(<ForYouToday />, {
      fetch: (url) => {
        if (url.includes('/api/ideas/today')) return { ideas, count: ideas.length };
        return {};
      },
    });
    expect(await rendered.findByTestId('foryou-accept-i1')).toBeInTheDocument();
    expect(await rendered.findByTestId('foryou-dismiss-i1')).toBeInTheDocument();
    expect(await rendered.findByTestId('foryou-accept-i2')).toBeInTheDocument();
  });
});
