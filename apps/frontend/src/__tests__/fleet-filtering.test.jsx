import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * AGT-17 on the page itself: the filters have to exist, be reachable by label,
 * survive in the URL, and agree with the counts printed above the table.
 *
 * lib/fleetFilters is unit-tested separately (fleet-filters.test.js); this file
 * is about the wiring — that the page reads its filters from the URL, writes
 * them back, and hands the same rows to the table that the summary counted.
 */

const RECENT = new Date(Date.now() - 10_000).toISOString();
const LONG_AGO = new Date(Date.now() - 6 * 3600 * 1000).toISOString();

const roster = [
  {
    id: 1,
    status: 'active',
    hostname: 'edge-01',
    agent_version: '0.9.0',
    fingerprint: 'a'.repeat(32),
    os: 'linux',
    arch: 'amd64',
  },
  {
    id: 2,
    status: 'active',
    hostname: 'edge-02',
    agent_version: '0.8.1',
    fingerprint: 'b'.repeat(32),
    os: 'linux',
    arch: 'amd64',
  },
  {
    id: 3,
    status: 'active',
    hostname: 'branch-nas',
    agent_version: '0.9.0',
    fingerprint: 'c'.repeat(32),
    os: 'linux',
    arch: 'arm64',
  },
  {
    id: 4,
    status: 'active',
    hostname: 'noisy-01',
    agent_version: '0.9.0',
    fingerprint: 'd'.repeat(32),
    os: 'linux',
    arch: 'amd64',
  },
];

const presence = [
  {
    agent_id: 1,
    online: true,
    last_seen_at: RECENT,
    capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
    latest: { collected_at: RECENT, cpu_pct: 10 },
    spool_depth: 0,
  },
  {
    agent_id: 2,
    online: true,
    last_seen_at: RECENT,
    capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
    latest: { collected_at: RECENT, cpu_pct: 11 },
    spool_depth: 0,
  },
  {
    agent_id: 3,
    online: false,
    last_seen_at: LONG_AGO,
    capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
    latest: null,
    spool_depth: 0,
  },
  {
    agent_id: 4,
    online: true,
    last_seen_at: RECENT,
    capabilities: {
      host_telemetry: { enabled: true, config: { interval_s: 30 } },
      remote_probe: { enabled: true, config: {} },
    },
    latest: { collected_at: RECENT, cpu_pct: 12 },
    spool_depth: 4000,
  },
];

vi.mock('../api/agents', async () => {
  const actual = await vi.importActual('../api/agents');
  return {
    listAgents: vi.fn(),
    getAgentsPresence: vi.fn(),
    getAgentsMetricsSeries: vi.fn(),
    getInstallCommand: vi.fn(),
    lookupPairingCode: vi.fn(),
    revokeAgent: vi.fn(),
    deleteAgent: vi.fn(),
    getAgent: vi.fn(),
    approveAgent: vi.fn(),
    getCapabilityDefaults: vi.fn(),
    rejectAgent: vi.fn(),
    normalizeCapability: actual.normalizeCapability,
  };
});

const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));
vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() }),
}));
vi.mock('../components/agents/ServerKeyRotationPanel', () => ({ default: () => null }));
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { role: 'admin' } }) }));

import * as api from '../api/agents';
import AgentsPage from '../pages/AgentsPage';

const renderAt = (entry = '/agents') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <AgentsPage />
    </MemoryRouter>
  );

/** Hostnames of the fleet rows currently rendered, in table order. */
const visibleHosts = () => {
  const table = screen.getByRole('table');
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => row.textContent)
    .map((text) => roster.find((agent) => text.includes(agent.hostname))?.hostname)
    .filter(Boolean);
};

beforeEach(() => {
  vi.clearAllMocks();
  mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
  api.listAgents.mockResolvedValue({ data: roster });
  api.getAgentsPresence.mockResolvedValue({ data: presence });
  api.getAgentsMetricsSeries.mockResolvedValue({ data: [] });
  api.getInstallCommand.mockResolvedValue({
    data: { tls_mode: 'self_signed', command: 'curl ...', script_sha256: 'x' },
  });
  api.getCapabilityDefaults.mockResolvedValue({ data: {} });
});

describe('the fleet filters', () => {
  it('offers every AGT-17 axis, each reachable by its label', async () => {
    renderAt();
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
    ['Find', 'Status', 'Capability', 'Online', 'Health', 'Version', 'Spool'].forEach((label) =>
      expect(screen.getByLabelText(label), label).toBeInTheDocument()
    );
  });

  it('filters to the agents behind the newest version in the fleet', async () => {
    renderAt();
    await waitFor(() => expect(visibleHosts()).toHaveLength(4));

    fireEvent.change(screen.getByLabelText('Version'), { target: { value: 'behind' } });
    await waitFor(() => expect(visibleHosts()).toEqual(['edge-02']));
  });

  it('filters to the agents holding a spool backlog', async () => {
    renderAt();
    await waitFor(() => expect(visibleHosts()).toHaveLength(4));

    fireEvent.change(screen.getByLabelText('Spool'), { target: { value: 'pressure' } });
    await waitFor(() => expect(visibleHosts()).toEqual(['noisy-01']));
  });

  it('collects everything that needs a human behind one health filter', async () => {
    renderAt();
    await waitFor(() => expect(visibleHosts()).toHaveLength(4));

    fireEvent.change(screen.getByLabelText('Health'), { target: { value: 'attention' } });
    // branch-nas is offline; noisy-01 is buffering. The two quiet ones are not.
    await waitFor(() => expect(visibleHosts().sort()).toEqual(['branch-nas', 'noisy-01']));
  });

  it('finds one machine by free text', async () => {
    renderAt();
    await waitFor(() => expect(visibleHosts()).toHaveLength(4));

    fireEvent.change(screen.getByLabelText('Find'), { target: { value: 'nas' } });
    await waitFor(() => expect(visibleHosts()).toEqual(['branch-nas']));
  });

  it('restores a filtered view straight from the URL', async () => {
    // What makes a filtered fleet shareable rather than a per-session accident.
    renderAt('/agents?online=offline');
    await waitFor(() => expect(visibleHosts()).toEqual(['branch-nas']));
    expect(screen.getByLabelText('Online')).toHaveValue('offline');
  });

  it('ignores a filter value that is not in the vocabulary', async () => {
    renderAt('/agents?health=perfect');
    await waitFor(() => expect(visibleHosts()).toHaveLength(4));
    expect(screen.getByLabelText('Health')).toHaveValue('all');
  });
});

describe('the counts above the table', () => {
  it('agrees with the rows the table is showing, before and after filtering', async () => {
    renderAt();
    await waitFor(() => expect(visibleHosts()).toHaveLength(4));
    expect(screen.getByRole('status', { name: '' }).textContent).toContain('4 of 4 agents');

    fireEvent.change(screen.getByLabelText('Version'), { target: { value: 'behind' } });
    await waitFor(() => expect(visibleHosts()).toEqual(['edge-02']));
    const summary = screen
      .getAllByRole('status')
      .map((el) => el.textContent)
      .join(' ');
    expect(summary).toContain('1 of 4 agents');
  });

  it('names the conditions worth filtering by, counted over the whole fleet', async () => {
    renderAt();
    await waitFor(() => expect(visibleHosts()).toHaveLength(4));
    const summary = screen
      .getAllByRole('status')
      .map((el) => el.textContent)
      .join(' ');
    expect(summary).toContain('1 offline');
    expect(summary).toContain('2 need attention');
    expect(summary).toContain('1 behind newest');
    expect(summary).toContain('1 with a spool backlog');
  });
});
