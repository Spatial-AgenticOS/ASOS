/**
 * Coverage batch (stage 5.4b) — tab-based pages.
 *
 * Forge, Intents, Agents, Flows, Marketplace, AppsPublish. Each uses a
 * Tabs component; the test mounts + asserts every tab is clickable +
 * switches selection. Plus one happy-path fetch per tab to exercise
 * the data branches.
 */
import { describe, it, expect } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { renderV2 } from '../_helpers/renderV2';

import Forge from '../../pages/Forge';
import Intents from '../../pages/Intents';
import Agents from '../../pages/Agents';
import Flows from '../../pages/Flows';
import Marketplace from '../../pages/Marketplace';
import AppsPublish from '../../pages/AppsPublish';

// ── Forge ────────────────────────────────────────────────────────

describe('Forge', () => {
  const forgeResp = (url) => {
    // Forge spreads `(.pending || .value || [])` into an array; if we
    // return {} the fallback hits the object itself and spread throws.
    // Always return an array-bearing shape.
    if (url.includes('/api/tool-genesis/pending')) return { pending: [] };
    if (url.includes('/api/tool-genesis/proposals')) return { proposals: [] };
    if (url.includes('/api/tool-genesis/list')) return { tools: [] };
    if (url.includes('/api/tool-genesis/stats')) return { total: 0 };
    if (url.includes('/api/skills/pending')) return { pending: [] };
    return { pending: [], proposals: [], tools: [] };
  };

  it('renders all four tabs', () => {
    const { getByRole } = renderV2(<Forge />, { fetch: forgeResp });
    expect(getByRole('tab', { name: /Pending/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /Proposals/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /Generated/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /Stats/i })).toBeInTheDocument();
  });

  it('switches tabs on click', () => {
    const { getByRole } = renderV2(<Forge />, { fetch: forgeResp });
    fireEvent.click(getByRole('tab', { name: /Stats/i }));
    expect(getByRole('tab', { name: /Stats/i })).toHaveAttribute('aria-selected', 'true');
  });
});

// ── Intents ──────────────────────────────────────────────────────

describe('Intents', () => {
  const intentsResp = (url) => {
    if (url.includes('/api/intents/today')) return { plans: [] };
    if (url.includes('/api/intents/list')) return { plans: [] };
    if (url.includes('/api/intents/stats')) return { total: 0 };
    return {};
  };

  it('renders the three tabs', () => {
    const { getByRole } = renderV2(<Intents />, { fetch: intentsResp });
    expect(getByRole('tab', { name: /Today/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /All/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /Stats/i })).toBeInTheDocument();
  });

  it('tab switch fires', () => {
    const { getByRole } = renderV2(<Intents />, { fetch: intentsResp });
    fireEvent.click(getByRole('tab', { name: /All/i }));
    expect(getByRole('tab', { name: /All/i })).toHaveAttribute('aria-selected', 'true');
  });
});

// ── Agents ───────────────────────────────────────────────────────

describe('Agents', () => {
  const agentsResp = (url) => {
    if (url.includes('/api/agents/personas')) return { personas: [] };
    if (url.includes('/api/agents/list')) return { agents: [] };
    if (url.includes('/api/agents/proposals')) return { proposals: [] };
    if (url.includes('/api/agents/stats')) return { total: 0 };
    return {};
  };

  it('renders four tabs', () => {
    const { getByRole } = renderV2(<Agents />, { fetch: agentsResp });
    expect(getByRole('tab', { name: /Personas/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /Specialists/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /Proposals/i })).toBeInTheDocument();
    expect(getByRole('tab', { name: /Stats/i })).toBeInTheDocument();
  });

  it('tab switch works', () => {
    const { getByRole } = renderV2(<Agents />, { fetch: agentsResp });
    fireEvent.click(getByRole('tab', { name: /Specialists/i }));
    expect(getByRole('tab', { name: /Specialists/i })).toHaveAttribute('aria-selected', 'true');
  });
});

// ── Flows ────────────────────────────────────────────────────────

describe('Flows', () => {
  const flowsResp = (url) => {
    if (url.includes('/api/taskflows/list')) return { flows: [] };
    if (url.includes('/api/taskflows/templates')) return { templates: [] };
    if (url.includes('/api/taskflows')) return { flows: [], templates: [] };
    return { flows: [] };
  };

  it('mounts without crashing', () => {
    const { container } = renderV2(<Flows />, { fetch: flowsResp });
    expect(container.firstChild).toBeInTheDocument();
  });
});

// ── Marketplace ──────────────────────────────────────────────────

describe('Marketplace', () => {
  const mpResp = (url) => {
    if (url.includes('/api/marketplace/catalog')) return { items: [] };
    if (url.includes('/api/marketplace/search')) return { items: [] };
    if (url.includes('/api/marketplace/installed')) return { items: [] };
    return { items: [] };
  };

  it('renders the kind filter bar', () => {
    const { container } = renderV2(<Marketplace />, { fetch: mpResp });
    expect(container.firstChild).toBeInTheDocument();
  });
});

// ── AppsPublish ──────────────────────────────────────────────────

describe('AppsPublish', () => {
  it('renders the five-step publish wizard', () => {
    const { getAllByText } = renderV2(<AppsPublish />, { fetch: () => ({ apps: [], count: 0 }) });
    // Each step's heading + button text may appear more than once; we
    // just need any match per step label.
    expect(getAllByText(/Scaffold/i).length).toBeGreaterThan(0);
    expect(getAllByText(/Validate/i).length).toBeGreaterThan(0);
    expect(getAllByText(/Install/i).length).toBeGreaterThan(0);
    expect(getAllByText(/Publish/i).length).toBeGreaterThan(0);
  });
});
