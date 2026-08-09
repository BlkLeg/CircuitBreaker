/**
 * The *production* path into discovery history.
 *
 * `discovery-execution-location.test.jsx` renders `DiscoveryHistoryPage`
 * directly and hands it an `agents` array. That is a component contract test:
 * it proves the row can name an agent, not that anything in the product ever
 * gives it a fleet to name one from. The page's only real call site is
 * `DiscoveryPage`, so every assertion here starts from `DiscoveryPage` — and,
 * for the `?agent=` filter and the `/discovery/history` redirect, from the URL
 * rather than from a prop.
 */
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('../api/discovery.js', () => ({
  getProfiles: vi.fn(),
  getJobs: vi.fn(),
  getJob: vi.fn(),
  getJobResults: vi.fn(),
  getJobLogs: vi.fn(),
  cancelJob: vi.fn(),
  enrichOpnsenseJob: vi.fn(),
  getPendingResults: vi.fn(),
  getDiscoveryStatus: vi.fn(),
  startAdHocScan: vi.fn(),
  pauseDiscovery: vi.fn(),
  resumeDiscovery: vi.fn(),
}));

vi.mock('../api/agents.js', () => ({
  listAgents: vi.fn(),
  getAgentDiscovery: vi.fn(),
}));

vi.mock('../api/client.jsx', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  systemApi: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));

vi.mock('../utils/logger.js', () => ({
  __esModule: true,
  default: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

// The sidebar polls listeners and host stats of its own; none of that is what
// these tests are about. Same stand-in as `discovery-page.test.jsx`.
vi.mock('../components/discovery/DiscoverySidebar.jsx', () => ({
  default: () => React.createElement('nav', { 'data-testid': 'discovery-sidebar' }),
}));

// Only needed by the redirect test, which imports `App.jsx`: `LoadingScreen`
// pulls in lottie-web, which cannot initialise under jsdom's canvas stub.
vi.mock('../components/common/LoadingScreen.jsx', () => ({
  default: () => React.createElement('div', null, 'loading'),
}));

import DiscoveryPage from '../pages/DiscoveryPage.jsx';
import { DiscoveryHistoryRedirect } from '../App.jsx';
import {
  getDiscoveryStatus,
  getJobs,
  getJobLogs,
  getJobResults,
  getPendingResults,
  getProfiles,
  pauseDiscovery,
  resumeDiscovery,
} from '../api/discovery.js';
import { getAgentDiscovery, listAgents } from '../api/agents.js';

// `AgentOut` as the fleet list returns it, with `hostname` alongside `name` and
// deliberately different from it, so "the operator's name wins" is observable
// rather than an artefact of the two strings matching.
const FLEET = [
  { id: 7, name: 'edge-agent-01', hostname: 'agent-7.lan' },
  { id: 9, name: 'branch-agent', hostname: 'agent-9.lan' },
];

/** What enrollment actually produces: a hostname, and no name at all. */
const UNNAMED_FLEET = [
  { id: 7, name: null, hostname: 'branch-office-01' },
  { id: 9, name: null, hostname: 'closet-pi-02' },
];

function agentJob(overrides = {}) {
  return {
    id: 601,
    status: 'completed',
    source_type: 'agent',
    scan_agent_id: 7,
    started_at: '2026-08-08T11:00:00Z',
    target_cidr: '192.168.5.0/24',
    scan_types_json: '["agent_connect"]',
    hosts_found: 3,
    hosts_new: 3,
    hosts_conflict: 0,
    ...overrides,
  };
}

function renderDiscoveryPage(entry = '/discovery') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <DiscoveryPage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getProfiles.mockResolvedValue({ data: [] });
  getJobs.mockResolvedValue({ data: [] });
  getJobResults.mockResolvedValue({ data: [] });
  getJobLogs.mockResolvedValue({ data: [] });
  getPendingResults.mockResolvedValue({ data: { total: 0 } });
  getDiscoveryStatus.mockResolvedValue({ data: {} });
  listAgents.mockResolvedValue({ data: FLEET });
  getAgentDiscovery.mockResolvedValue({ data: { agent_id: 7, globally_paused: false } });
  pauseDiscovery.mockResolvedValue({ data: { paused: true } });
  resumeDiscovery.mockResolvedValue({ data: { paused: false } });
});

describe('DiscoveryPage — the agent name in job history', () => {
  it('names the agent a scan ran on, through the page that actually renders history', async () => {
    getJobs.mockResolvedValue({ data: [agentJob()] });

    renderDiscoveryPage();

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    const link = await screen.findByRole('link', { name: 'edge-agent-01' });
    expect(link).toHaveAttribute('href', '/agents/7');
    // The defect this test exists for: the fleet never reached the table, so
    // every agent-executed row read "agent 7".
    expect(screen.queryByText('agent 7')).not.toBeInTheDocument();
  });

  it('names an un-renamed agent by its hostname, not by its id', async () => {
    // `agents.name` is nullable and enrollment never writes it —
    // `ws_agents.enroll_stream` calls `agent_registry.create_pending_agent`
    // with hostname/os/arch and no name, and the only writer is an explicit
    // operator `PATCH /agents/{id}`. So `FLEET` above is the *renamed* minority
    // and this is the fleet an operator who has renamed nothing actually has;
    // the plumbing fixed last pass carries a null for all of them.
    listAgents.mockResolvedValue({ data: UNNAMED_FLEET });
    getJobs.mockResolvedValue({ data: [agentJob()] });

    renderDiscoveryPage();

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    expect(await screen.findByRole('link', { name: 'branch-office-01' })).toHaveAttribute(
      'href',
      '/agents/7'
    );
    expect(screen.queryByText('agent 7')).not.toBeInTheDocument();
  });

  it('still renders the row when the fleet request fails', async () => {
    getJobs.mockResolvedValue({ data: [agentJob()] });
    listAgents.mockRejectedValue(new Error('boom'));

    renderDiscoveryPage();

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'agent 7' })).toHaveAttribute('href', '/agents/7');
  });
});

describe('DiscoveryPage — the ?agent= deep link', () => {
  it('filters history to the agent named in the query string', async () => {
    getJobs.mockResolvedValue({
      data: [
        agentJob({ id: 601, scan_agent_id: 7, target_cidr: '192.168.5.0/24' }),
        agentJob({ id: 602, scan_agent_id: 9, target_cidr: '192.168.6.0/24' }),
        agentJob({
          id: 603,
          scan_agent_id: null,
          source_type: 'manual',
          target_cidr: '10.0.0.0/24',
        }),
      ],
    });

    renderDiscoveryPage('/discovery?agent=9');

    await waitFor(() => expect(screen.getByText('192.168.6.0/24')).toBeInTheDocument());
    expect(screen.queryByText('192.168.5.0/24')).not.toBeInTheDocument();
    expect(screen.queryByText('10.0.0.0/24')).not.toBeInTheDocument();
  });

  it('says whose history it is showing, and can drop the filter', async () => {
    getJobs.mockResolvedValue({
      data: [
        agentJob({ id: 601, scan_agent_id: 7, target_cidr: '192.168.5.0/24' }),
        agentJob({ id: 602, scan_agent_id: 9, target_cidr: '192.168.6.0/24' }),
      ],
    });

    renderDiscoveryPage('/discovery?agent=9');

    const banner = await screen.findByRole('status', { name: 'Discovery history filter' });
    expect(within(banner).getByText(/branch-agent/)).toBeInTheDocument();

    fireEvent.click(within(banner).getByRole('button', { name: 'Show all scans' }));

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    expect(screen.queryByRole('status', { name: 'Discovery history filter' })).toBeNull();
  });

  it('names an un-renamed agent by hostname in the filter banner', async () => {
    // The banner resolves the fleet independently of the history table, so it
    // is its own chance to say "agent 9" while the rows above say otherwise.
    listAgents.mockResolvedValue({ data: UNNAMED_FLEET });
    getJobs.mockResolvedValue({
      data: [agentJob({ id: 602, scan_agent_id: 9, target_cidr: '192.168.6.0/24' })],
    });

    renderDiscoveryPage('/discovery?agent=9');

    const banner = await screen.findByRole('status', { name: 'Discovery history filter' });
    expect(within(banner).getByText(/closet-pi-02/)).toBeInTheDocument();
    expect(within(banner).queryByText(/agent 9/i)).not.toBeInTheDocument();
  });

  it('falls back to the id when the filtered agent is not in the fleet', async () => {
    // Nothing constrains `?agent=` to an agent that still exists, and a banner
    // that rendered "Showing discovery history for " with nothing after it is
    // worse than one that names the id.
    listAgents.mockResolvedValue({ data: [] });
    getJobs.mockResolvedValue({
      data: [agentJob({ id: 602, scan_agent_id: 9, target_cidr: '192.168.6.0/24' })],
    });

    renderDiscoveryPage('/discovery?agent=9');

    const banner = await screen.findByRole('status', { name: 'Discovery history filter' });
    expect(within(banner).getByText(/agent 9/)).toBeInTheDocument();
  });

  it('ignores an ?agent= value that is not an agent id', async () => {
    getJobs.mockResolvedValue({ data: [agentJob()] });

    renderDiscoveryPage('/discovery?agent=not-a-number');

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    expect(screen.queryByRole('status', { name: 'Discovery history filter' })).toBeNull();
  });
});

describe('App — /discovery/history', () => {
  function LocationProbe() {
    const { pathname, search } = useLocation();
    return <div data-testid="probe">{`${pathname}${search}`}</div>;
  }

  it('keeps the query string when it redirects to /discovery', () => {
    render(
      <MemoryRouter initialEntries={['/discovery/history?agent=3']}>
        <Routes>
          <Route path="/discovery" element={<LocationProbe />} />
          <Route path="/discovery/history" element={<DiscoveryHistoryRedirect />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByTestId('probe')).toHaveTextContent('/discovery?agent=3');
  });
});

describe('DiscoveryPage — the fleet-wide discovery hold', () => {
  it('shows the fleet-wide hold and releases it', async () => {
    getAgentDiscovery.mockResolvedValue({ data: { agent_id: 7, globally_paused: true } });

    renderDiscoveryPage();

    const region = await screen.findByRole('region', { name: 'Agent discovery' });
    expect(within(region).getByText(/paused fleet-wide/i)).toBeInTheDocument();

    fireEvent.click(within(region).getByRole('button', { name: 'Resume agent discovery' }));

    await waitFor(() => expect(resumeDiscovery).toHaveBeenCalledTimes(1));
    expect(
      await within(region).findByRole('button', { name: 'Pause agent discovery' })
    ).toBeInTheDocument();
  });

  it('holds the fleet from the running state', async () => {
    renderDiscoveryPage();

    const region = await screen.findByRole('region', { name: 'Agent discovery' });
    expect(within(region).queryByText(/paused fleet-wide/i)).toBeNull();

    fireEvent.click(within(region).getByRole('button', { name: 'Pause agent discovery' }));

    await waitFor(() => expect(pauseDiscovery).toHaveBeenCalledTimes(1));
    expect(
      await within(region).findByRole('button', { name: 'Resume agent discovery' })
    ).toBeInTheDocument();
    expect(within(region).getByText(/paused fleet-wide/i)).toBeInTheDocument();
  });

  it('offers no fleet-wide control when there are no agents', async () => {
    listAgents.mockResolvedValue({ data: [] });

    renderDiscoveryPage();

    await waitFor(() => expect(listAgents).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'Agent discovery' })).toBeNull();
    expect(getAgentDiscovery).not.toHaveBeenCalled();
  });
});
