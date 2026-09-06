import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';

// Slice 3 Task 21. Same discipline as agent-detail-page.test.jsx: every default
// implementation lives in this hoisted object and is re-applied in beforeEach,
// because vi.clearAllMocks() clears call records but leaves implementations
// installed — a mockResolvedValue set by one test would otherwise become the
// fixture for every test after it.
const apiDefaults = vi.hoisted(() => {
  const agent = {
    id: 3,
    name: 'branch-office',
    hostname: 'box1',
    status: 'active',
    fingerprint: 'a'.repeat(32),
    agent_version: '0.1.0',
    capabilities: {
      host_telemetry: false,
      local_discovery: false,
      remote_probe: {
        enabled: true,
        config: {
          max_concurrent: 20,
          scope_mode: 'direct_private',
          excluded_cidrs: [],
          additional_cidrs: [],
          additional_hostnames: [],
        },
      },
    },
  };
  const probes = {
    agent_id: 3,
    max_concurrent: 20,
    active_runs: 2,
    assignments: [
      {
        monitor_id: 41,
        name: 'lab gateway',
        check_type: 'icmp',
        host: '10.0.0.1',
        target_type: null,
        target_id: null,
        interval_secs: 60,
        enabled: true,
        // Target state and execution condition side by side. The agent is
        // offline, so the last known target state is still `up` — that is the
        // whole point of §7's separation.
        status: 'up',
        probe_execution_status: 'unavailable',
        probe_execution_reason: 'agent_offline',
        probe_last_dispatched_at: '2026-08-06T09:00:00Z',
        probe_last_result_at: '2026-08-06T08:59:00Z',
      },
      {
        monitor_id: 42,
        name: 'lab dns',
        check_type: 'dns',
        host: 'ns.lab.internal',
        target_type: null,
        target_id: null,
        interval_secs: 300,
        enabled: true,
        status: 'down',
        probe_execution_status: 'ready',
        probe_execution_reason: null,
        probe_last_dispatched_at: null,
        probe_last_result_at: null,
      },
    ],
  };
  return {
    agent,
    probes,
    getAgent: () => Promise.resolve({ data: structuredClone(agent) }),
    getAgentEvents: () => Promise.resolve({ data: [] }),
    getAgentProbes: () => Promise.resolve({ data: structuredClone(probes) }),
    getAgentTelemetry: () => Promise.resolve({ data: { latest: null, readiness: [] } }),
    getAgentTelemetryHistory: () => Promise.resolve({ data: { points: [] } }),
    getAgentsPresence: () =>
      Promise.resolve({
        data: [{ agent_id: 3, online: true, connected_since: null, hardware: null }],
      }),
    getCapabilityDefaults: () =>
      Promise.resolve({
        data: {
          host_telemetry: { enabled: true, config: { interval_s: 45 } },
          remote_probe: {
            enabled: true,
            config: {
              max_concurrent: 20,
              scope_mode: 'direct_private',
              excluded_cidrs: [],
              additional_cidrs: [],
              additional_hostnames: [],
            },
          },
          local_discovery: { enabled: true, config: {} },
        },
      }),
    setAgentCapabilities: () => Promise.resolve({ data: structuredClone(agent) }),
    revokeAgent: () => Promise.resolve({ data: {} }),
    triggerAgentUpdate: () => Promise.resolve({ data: {} }),
    listProbeEligibleAgents: () =>
      Promise.resolve({
        data: [
          {
            agent_id: 3,
            name: 'branch-office',
            online: true,
            granted: true,
            readiness: 'ready',
            readiness_collector: 'probe.icmp',
            max_concurrent: 20,
            active_runs: 2,
            assigned_monitors: 2,
            scope_version: 'v1',
            scope_networks: ['10.0.0.0/24'],
            excluded_networks: [],
            in_scope: true,
            eligible: true,
            reason: null,
          },
          {
            agent_id: 9,
            name: 'warehouse',
            online: true,
            granted: true,
            readiness: 'ready',
            readiness_collector: 'probe.icmp',
            max_concurrent: 20,
            active_runs: 0,
            assigned_monitors: 0,
            scope_version: 'v1',
            scope_networks: ['10.0.0.0/24'],
            excluded_networks: [],
            in_scope: true,
            eligible: true,
            reason: null,
          },
          {
            agent_id: 11,
            name: 'dmz',
            online: false,
            granted: true,
            readiness: null,
            readiness_collector: 'probe.icmp',
            max_concurrent: 20,
            active_runs: 0,
            assigned_monitors: 0,
            scope_version: 'v1',
            scope_networks: [],
            excluded_networks: [],
            in_scope: false,
            eligible: false,
            reason: 'agent_offline',
          },
        ],
      }),
    runCheck: () => Promise.resolve({ data: {} }),
    updateMonitor: () => Promise.resolve({ data: {} }),
  };
});

vi.mock('../api/agents', () => ({
  normalizeCapability: (value) =>
    typeof value === 'boolean'
      ? { enabled: value, config: {} }
      : { enabled: Boolean(value?.enabled), config: value?.config ?? {} },
  getAgent: vi.fn(apiDefaults.getAgent),
  getAgentEvents: vi.fn(apiDefaults.getAgentEvents),
  getAgentProbes: vi.fn(apiDefaults.getAgentProbes),
  getAgentTelemetry: vi.fn(apiDefaults.getAgentTelemetry),
  getAgentTelemetryHistory: vi.fn(apiDefaults.getAgentTelemetryHistory),
  getAgentsPresence: vi.fn(apiDefaults.getAgentsPresence),
  getCapabilityDefaults: vi.fn(apiDefaults.getCapabilityDefaults),
  setAgentCapabilities: vi.fn(apiDefaults.setAgentCapabilities),
  revokeAgent: vi.fn(apiDefaults.revokeAgent),
  triggerAgentUpdate: vi.fn(apiDefaults.triggerAgentUpdate),
  listProbeEligibleAgents: vi.fn(apiDefaults.listProbeEligibleAgents),
  // Slice 4 Task 27: AgentDetailPage now also loads GET /agents/{id}/discovery
  // for the Discovery scope section. Plain functions rather than vi.fn(): these
  // tests assert nothing about discovery, and a stub with no implementation
  // would throw inside the page's loader.
  getAgentDiscovery: () => Promise.resolve({ data: null }),
  pauseAgentDiscovery: () => Promise.resolve({ data: null }),
  resumeAgentDiscovery: () => Promise.resolve({ data: null }),
}));

vi.mock('../api/monitor', () => ({
  runCheck: vi.fn(apiDefaults.runCheck),
  updateMonitor: vi.fn(apiDefaults.updateMonitor),
}));

const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

const mockTelemetryStream = vi.hoisted(() => ({ data: new Map(), connected: true }));
vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => mockTelemetryStream,
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/agents/3']}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

/**
 * Task 14: the probes section is a tab, so it is only in the DOM once its tab
 * is selected. Selecting it is part of asking for the section.
 */
async function probesSection() {
  fireEvent.click(await screen.findByRole('tab', { name: 'Probes' }));
  return screen.findByRole('region', { name: 'Assigned probes' });
}

/** …and the capability toggles live on Overview, one tab back. */
async function openOverview() {
  fireEvent.click(await screen.findByRole('tab', { name: 'Overview' }));
  return screen.findByRole('region', { name: 'Capabilities' });
}

describe('Agent Detail — assigned probes', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const api = await import('../api/agents');
    api.getAgent.mockImplementation(apiDefaults.getAgent);
    api.getAgentEvents.mockImplementation(apiDefaults.getAgentEvents);
    api.getAgentProbes.mockImplementation(apiDefaults.getAgentProbes);
    api.getAgentTelemetry.mockImplementation(apiDefaults.getAgentTelemetry);
    api.getAgentTelemetryHistory.mockImplementation(apiDefaults.getAgentTelemetryHistory);
    api.getAgentsPresence.mockImplementation(apiDefaults.getAgentsPresence);
    api.getCapabilityDefaults.mockImplementation(apiDefaults.getCapabilityDefaults);
    api.setAgentCapabilities.mockImplementation(apiDefaults.setAgentCapabilities);
    api.revokeAgent.mockImplementation(apiDefaults.revokeAgent);
    api.triggerAgentUpdate.mockImplementation(apiDefaults.triggerAgentUpdate);
    api.listProbeEligibleAgents.mockImplementation(apiDefaults.listProbeEligibleAgents);
    const monitorApi = await import('../api/monitor');
    monitorApi.runCheck.mockImplementation(apiDefaults.runCheck);
    monitorApi.updateMonitor.mockImplementation(apiDefaults.updateMonitor);
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    mockTelemetryStream.data = new Map();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('lists assigned monitors with type, target, interval, target state and execution condition', async () => {
    renderDetail();

    const section = await probesSection();
    const row = within(section).getByRole('row', { name: /lab gateway/ });
    expect(within(row).getByText('icmp')).toBeInTheDocument();
    expect(within(row).getByText('10.0.0.1')).toBeInTheDocument();
    expect(within(row).getByText('60s')).toBeInTheDocument();
    // Target state is the last known one, untouched by the execution
    // condition beside it — the load-bearing rule of §7.
    expect(within(row).getByText('up')).toBeInTheDocument();
    expect(within(row).getByText(/Probe unavailable — agent offline/)).toBeInTheDocument();

    const ready = within(section).getByRole('row', { name: /lab dns/ });
    expect(within(ready).getByText('down')).toBeInTheDocument();
    expect(within(ready).getByText('Ready')).toBeInTheDocument();
    expect(within(ready).getByText('Never')).toBeInTheDocument();
  });

  it('shows concurrency used against the configured limit', async () => {
    renderDetail();

    const section = await probesSection();
    expect(
      within(section).getByText(/2 of 20 concurrent checks in use · 2 assigned/)
    ).toBeInTheDocument();
  });

  it('keeps the disabled-probing wording exactly as written', async () => {
    // Task 18 moved this sentence into a Banner. It is the operator's only
    // explanation of why assignments are listed but nothing is running, so
    // the assertion is byte for byte: a later tidy-up fails here rather than
    // drifting.
    const { getAgent } = await import('../api/agents');
    getAgent.mockResolvedValue({
      data: {
        ...apiDefaults.agent,
        capabilities: { ...apiDefaults.agent.capabilities, remote_probe: false },
      },
    });
    renderDetail();

    const section = await probesSection();
    expect(
      within(section).getByText(
        'Remote probing is disabled for this agent. Assigned monitors keep their last known target state and stay probe-unavailable until it is re-enabled.'
      )
    ).toBeInTheDocument();
  });

  it('is reachable as a region by its heading', async () => {
    renderDetail();
    // Panel names the region from its own title, so the section stays
    // navigable by heading rather than by an aria-label a refactor can drop.
    expect(await probesSection()).toBeInTheDocument();
  });

  it('offers open, check now, reassign and return-to-server actions', async () => {
    const { runCheck, updateMonitor } = await import('../api/monitor');
    const { listProbeEligibleAgents } = await import('../api/agents');
    renderDetail();

    const section = await probesSection();
    const row = within(section).getByRole('row', { name: /lab gateway/ });

    expect(within(row).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/monitors/41');

    fireEvent.click(within(row).getByRole('button', { name: 'Check now' }));
    await waitFor(() => expect(runCheck).toHaveBeenCalledWith(41));

    fireEvent.click(within(row).getByRole('button', { name: 'Reassign' }));
    await waitFor(() => expect(listProbeEligibleAgents).toHaveBeenCalledWith({ monitor_id: 41 }));
    const select = await within(row).findByRole('combobox', { name: 'Reassign lab gateway' });
    // This agent is filtered out of its own reassign list; an ineligible
    // candidate still renders, disabled, with its machine-readable reason.
    expect(within(select).queryByRole('option', { name: /branch-office/ })).toBeNull();
    expect(within(select).getByRole('option', { name: /dmz — agent offline/ })).toBeDisabled();
    fireEvent.change(select, { target: { value: '9' } });
    await waitFor(() => expect(updateMonitor).toHaveBeenCalledWith(41, { probe_agent_id: 9 }));

    fireEvent.click(within(row).getByRole('button', { name: 'Return to server' }));
    await waitFor(() => expect(updateMonitor).toHaveBeenCalledWith(41, { probe_agent_id: null }));
  });

  it('disabling remote probing with assignments asks for confirmation and explains state retention', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    renderDetail();

    await probesSection();
    await openOverview();
    fireEvent.click(await screen.findByLabelText('Remote probe'));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent(/2 assigned monitors will stay assigned/);
    expect(dialog).toHaveTextContent(/retain their last known target state/);
    expect(dialog).toHaveTextContent(/probe-unavailable/);
    // Nothing is written until the user confirms.
    expect(setAgentCapabilities).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith('3', { remote_probe: false })
    );
  });

  it('disabling with no assignments does not prompt', async () => {
    const { getAgentProbes, setAgentCapabilities } = await import('../api/agents');
    getAgentProbes.mockResolvedValue({
      data: { agent_id: 3, max_concurrent: 20, active_runs: 0, assignments: [] },
    });
    renderDetail();

    const section = await probesSection();
    await within(section).findByText(/0 of 20 concurrent checks in use/);

    await openOverview();
    fireEvent.click(await screen.findByLabelText('Remote probe'));
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith('3', { remote_probe: false })
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('remote probe config editor rejects max_concurrent outside 1-100 before calling the API', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    renderDetail();

    await probesSection();
    const input = await screen.findByLabelText(/Concurrent checks/);
    expect(input).toHaveValue(20);

    fireEvent.change(input, { target: { value: '101' } });
    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith('Concurrent checks must be between 1 and 100')
    );
    fireEvent.change(input, { target: { value: '0' } });
    await waitFor(() => expect(mockToast.error).toHaveBeenCalledTimes(2));

    expect(setAgentCapabilities).not.toHaveBeenCalled();
  });

  it('an invalid config rolls back to the previous value', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    setAgentCapabilities.mockRejectedValue({
      response: { data: { detail: 'additional_cidrs may not contain a default route' } },
    });
    renderDetail();

    await probesSection();
    const input = await screen.findByLabelText(/Concurrent checks/);

    fireEvent.change(input, { target: { value: '50' } });
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith('3', {
        remote_probe: {
          enabled: true,
          config: {
            max_concurrent: 50,
            scope_mode: 'direct_private',
            excluded_cidrs: [],
            additional_cidrs: [],
            additional_hostnames: [],
          },
        },
      })
    );
    // The optimistic value is rolled back to what is actually persisted, and
    // the server's own reason is surfaced rather than a generic failure.
    await waitFor(() => expect(input).toHaveValue(20));
    expect(mockToast.error).toHaveBeenCalledWith(
      'additional_cidrs may not contain a default route'
    );
  });
});
