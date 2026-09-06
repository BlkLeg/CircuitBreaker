import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

const hookResult = {
  agent: {
    id: 7,
    status: 'active',
    hostname: 'edge-01',
    os: 'linux',
    arch: 'amd64',
    agent_version: '0.4.0',
    fingerprint: 'a'.repeat(32),
    last_seen_at: new Date().toISOString(),
    capabilities: {},
  },
  presence: { online: true, hardware: null },
  events: [],
  telemetry: null,
  history: [],
  probes: null,
  discovery: null,
  capabilityDefaults: {},
  loading: false,
  states: [{ code: 'online', label: 'Online', tone: 'ok', summary: 's', action: 'a' }],
  page: {
    primary: { code: 'online', label: 'Online', tone: 'ok', summary: 's', action: 'a' },
    secondary: [],
    showLiveStrip: true,
    liveStripDimmed: false,
    tabs: ['overview', 'telemetry', 'probes', 'discovery', 'events'],
    overviewPanels: ['capabilities', 'discovery', 'probes', 'hardware', 'events'],
    capabilitiesLocked: false,
    blockedReason: null,
  },
  freshness: { level: 'live', label: 'LIVE', ageSeconds: 3, animate: true },
  online: true,
  historyRange: '1h',
  setHistoryRange: vi.fn(),
  setDiscovery: vi.fn(),
  reload: vi.fn(),
  reloadTelemetry: vi.fn(),
  reloadProbes: vi.fn(),
  reloadDiscovery: vi.fn(),
};

vi.mock('../hooks/useAgentDetail', () => ({
  useAgentDetail: (...args) => {
    hookResult.calls.push(args);
    return hookResult;
  },
  POLL_ACTIVE_MS: 30000,
  POLL_BACKOFF_MS: 120000,
}));
vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}));

import AgentDetailPage from '../pages/AgentDetailPage';

function renderAt(url) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  hookResult.calls = [];
});

describe('agent detail tabs', () => {
  it('opens on overview when no tab is named', async () => {
    renderAt('/agents/7');
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Overview' })).toBeTruthy());
    expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe(
      'true'
    );
  });

  it('opens on the tab named in the URL', async () => {
    renderAt('/agents/7?tab=discovery');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Discovery' }).getAttribute('aria-selected')).toBe(
        'true'
      )
    );
  });

  it('falls back to overview for a tab name it does not know', async () => {
    // A stale bookmark or a hand-edited URL must not produce a blank page.
    renderAt('/agents/7?tab=nonsense');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe(
        'true'
      )
    );
  });

  it('writes the tab into the URL when one is clicked', async () => {
    renderAt('/agents/7');
    await userEvent.click(await screen.findByRole('tab', { name: 'Events' }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Events' }).getAttribute('aria-selected')).toBe('true')
    );
  });

  it('tells the data hook which tab is active, so gating can work', async () => {
    renderAt('/agents/7?tab=telemetry');
    await waitFor(() => expect(hookResult.calls.length).toBeGreaterThan(0));
    const [, options] = hookResult.calls.at(-1);
    expect(options.activeTab).toBe('telemetry');
  });

  it('renders one tabpanel, labelled by its tab', async () => {
    renderAt('/agents/7?tab=events');
    const panel = await screen.findByRole('tabpanel');
    expect(panel.id).toBe('cb-panel-events');
    expect(panel.getAttribute('aria-labelledby')).toBe('cb-tab-events');
  });

  it('keeps the live strip on a tab that has no telemetry of its own', async () => {
    // Spec 5.1: the pulse must not hide with the detail.
    const { container } = renderAt('/agents/7?tab=events');
    await waitFor(() => expect(container.querySelector('.agent-strip')).toBeTruthy());
    expect(screen.getByText('LIVE')).toBeTruthy();
  });

  it('corrects a link to a tab this agent does not have', async () => {
    // A bookmark saved before the agent was revoked. The name is spelled like a
    // tab, so TAB_KEYS alone would keep it — the composition is what says this
    // agent has no telemetry tab. Correcting it in the URL rather than clamping
    // at render is what keeps the hook's fetch gating and the rendered panel on
    // the same tab.
    hookResult.page = { ...hookResult.page, tabs: ['overview', 'events'] };
    renderAt('/agents/7?tab=telemetry');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe(
        'true'
      )
    );
    // …and the hook is told the tab that is actually showing, or it gates off
    // the very fetches the overview panel needs.
    const [, options] = hookResult.calls.at(-1);
    expect(options.activeTab).toBe('overview');
    hookResult.page = {
      ...hookResult.page,
      tabs: ['overview', 'telemetry', 'probes', 'discovery', 'events'],
    };
  });

  it('renders only the tabs the composition allows', async () => {
    hookResult.page = { ...hookResult.page, tabs: ['overview', 'events'] };
    renderAt('/agents/7');
    await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(2));
    hookResult.page = {
      ...hookResult.page,
      tabs: ['overview', 'telemetry', 'probes', 'discovery', 'events'],
    };
  });

  it('shows no live strip when the composition withholds it', async () => {
    hookResult.page = { ...hookResult.page, showLiveStrip: false };
    const { container } = renderAt('/agents/7');
    await waitFor(() => expect(screen.getByRole('tablist')).toBeTruthy());
    expect(container.querySelector('.agent-strip')).toBeNull();
    hookResult.page = { ...hookResult.page, showLiveStrip: true };
  });
});
