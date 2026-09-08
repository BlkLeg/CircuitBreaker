import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import {
  REGISTRY_HOST_CONFIG,
  renderDetail,
  openTab,
  telemetryFixture,
  findCards,
  cardValue,
} from './helpers/agentDetailHarness';

// Task 19: the default API responses live here rather than inline in the
// vi.mock factory so that beforeEach can *restore* them. `vi.clearAllMocks()`
// clears call records but leaves implementations installed, so a
// `mockResolvedValue` set by one test silently became the fixture for every
// test after it — the `hardware: null` presence override in the online/offline
// tests was reaching the telemetry tests below, and the never-resolving
// `getCapabilityDefaults` was reaching everything after it. Re-applying every
// implementation in beforeEach makes each test start from the same fixture.
const apiDefaults = vi.hoisted(() => {
  const agent = {
    id: 3,
    name: null,
    hostname: 'box1',
    status: 'active',
    fingerprint: 'a'.repeat(32),
    agent_version: '0.1.0',
    capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
  };
  return {
    agent,
    getAgent: () => Promise.resolve({ data: { ...agent } }),
    getAgentEvents: () =>
      Promise.resolve({
        data: [{ id: 1, event_type: 'approved', created_at: '2026-07-27T12:00:00Z', detail: null }],
      }),
    // Slice 3 Task 21: the page now also loads its assigned probes. Empty
    // here — the assigned-probes surface has its own suite
    // (agent-assigned-probes.test.jsx); this fixture only has to keep the
    // section from reporting a load failure in every unrelated test.
    getAgentProbes: () =>
      Promise.resolve({
        data: { agent_id: 3, max_concurrent: 20, active_runs: 0, assignments: [] },
      }),
    getAgentTelemetry: () => Promise.resolve({ data: { latest: null, readiness: [] } }),
    getAgentTelemetryHistory: () => Promise.resolve({ data: { points: [] } }),
    getAgentsPresence: () =>
      Promise.resolve({
        data: [
          {
            agent_id: 3,
            online: true,
            connected_since: '2026-08-04T10:00:00Z',
            last_seen_at: '2026-08-04T10:05:00Z',
            capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
            hardware: {
              id: 5,
              name: 'lab-nas',
              hostname: 'nas.local',
              ip_address: null,
              mac_address: null,
            },
          },
        ],
      }),
    // Task 14: HOST_DEFAULTS is gone from the page; the host-telemetry config
    // key list and every fallback value come from the server registry. This
    // fixture deliberately carries a key the frontend has never heard of
    // (`include_gpu`) so the test proves the page renders whatever the server
    // declares rather than a hardcoded copy.
    getCapabilityDefaults: () =>
      Promise.resolve({
        data: {
          host_telemetry: {
            enabled: true,
            config: {
              interval_s: 45,
              include_filesystems: true,
              include_disks: true,
              include_network: true,
              include_temperatures: true,
              include_virtual: false,
              include_docker: false,
              include_gpu: true,
            },
          },
          remote_probe: { enabled: true, config: {} },
          local_discovery: { enabled: true, config: {} },
        },
      }),
    setAgentCapabilities: () => Promise.resolve({ data: { ...agent } }),
    revokeAgent: () => Promise.resolve({ data: {} }),
    triggerAgentUpdate: () => Promise.resolve({ data: {} }),
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
  // Slice 4 Task 27: AgentDetailPage now also loads GET /agents/{id}/discovery
  // for the Discovery scope section. Plain functions rather than vi.fn(): these
  // tests assert nothing about discovery, and a stub with no implementation
  // would throw inside the page's loader.
  getAgentDiscovery: () => Promise.resolve({ data: null }),
  pauseAgentDiscovery: () => Promise.resolve({ data: null }),
  resumeAgentDiscovery: () => Promise.resolve({ data: null }),
}));

// See agents-page.test.jsx for why useAgentLive needs vi.hoisted() here.
const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

// Task 18: the page consumes the telemetry stream's `data` Map directly, so
// the tests drive it by swapping the Map. The returned object identity is
// stable across renders on purpose — a fresh object (or a fresh Map) per
// render would re-fire the live-update effects on every commit.
const mockTelemetryStream = vi.hoisted(() => ({ data: new Map(), connected: true }));
vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => mockTelemetryStream,
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

// The unverified-clock caveat is conditional on the offset having been
// measured, and nothing in this suite carries a Date header, so one test has to
// say it was. Only serverClockOffsetMs is replaced — lib/agentState's serverNow
// keeps the real implementation.
const mockClockOffsetMs = vi.hoisted(() => vi.fn(() => null));
vi.mock('../utils/serverClock', async (importOriginal) => ({
  ...(await importOriginal()),
  serverClockOffsetMs: mockClockOffsetMs,
}));

describe('AgentDetailPage', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    // clearAllMocks does NOT restore implementations; do it explicitly so no
    // test inherits another test's mockResolvedValue.
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
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    mockTelemetryStream.data = new Map();
    mockClockOffsetMs.mockReturnValue(null);
  });

  afterEach(() => {
    // The capability-editor tests stub window.confirm with vi.spyOn.
    vi.restoreAllMocks();
  });

  describe('host-telemetry capability editing', () => {
    /**
     * Task 16: the settings form is on the Telemetry tab (spec §7), so every
     * test here has to open it before the controls exist.
     */
    const renderSettings = async () => {
      renderDetail();
      await openTab('Telemetry');
    };

    // The client guard exists to match the agent-side bounds in
    // internal/capability/capability.go:14-17 (MinIntervalSeconds 10,
    // MaxIntervalSeconds 900). These two tests are what stop the pair drifting.
    it.each([
      ['below the minimum', '5'],
      ['above the maximum', '1000'],
    ])('rejects a cadence %s without calling the API', async (_label, value) => {
      const { setAgentCapabilities } = await import('../api/agents');

      await renderSettings();

      const cadence = await screen.findByLabelText(/cadence/i);
      fireEvent.change(cadence, { target: { value } });

      expect(mockToast.error).toHaveBeenCalledWith('Cadence must be between 10 and 900 seconds');
      expect(setAgentCapabilities).not.toHaveBeenCalled();
    });

    it('sends the registry-derived config merged with the patch for a valid cadence', async () => {
      const { setAgentCapabilities } = await import('../api/agents');

      await renderSettings();

      const cadence = await screen.findByLabelText(/cadence/i);
      fireEvent.change(cadence, { target: { value: '60' } });

      await waitFor(() => expect(setAgentCapabilities).toHaveBeenCalledTimes(1));
      expect(setAgentCapabilities).toHaveBeenCalledWith('3', {
        host_telemetry: {
          enabled: true,
          // The grant is a bare `true`, so every key comes from the *fetched*
          // defaults (Task 14 deleted HOST_DEFAULTS), with the patch on top.
          config: { ...REGISTRY_HOST_CONFIG, interval_s: 60 },
        },
      });
      expect(mockToast.error).not.toHaveBeenCalled();
    });

    it('restores the previous agent and surfaces the server detail when the update is rejected', async () => {
      const { setAgentCapabilities } = await import('../api/agents');
      setAgentCapabilities.mockRejectedValue({
        response: { data: { detail: 'interval_s must be an integer' } },
      });

      await renderSettings();

      const virtual = await screen.findByLabelText(/^virtual$/i);
      expect(virtual).not.toBeChecked();
      fireEvent.click(virtual);

      // Optimistic flip, then rollback.
      await waitFor(() =>
        expect(mockToast.error).toHaveBeenCalledWith('interval_s must be an integer')
      );
      expect(screen.getByLabelText(/^virtual$/i)).not.toBeChecked();
    });

    it('falls back to a generic message when the rejection carries no server detail', async () => {
      const { setAgentCapabilities } = await import('../api/agents');
      setAgentCapabilities.mockRejectedValue(new Error('network down'));

      await renderSettings();

      fireEvent.click(await screen.findByLabelText(/^virtual$/i));

      await waitFor(() =>
        expect(mockToast.error).toHaveBeenCalledWith('Could not update telemetry settings')
      );
    });

    it('aborts before any request when the Docker socket confirmation is declined', async () => {
      const { setAgentCapabilities } = await import('../api/agents');
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

      await renderSettings();

      const docker = await screen.findByLabelText(/^docker$/i);
      expect(docker).not.toBeChecked();
      fireEvent.click(docker);

      expect(confirmSpy).toHaveBeenCalledTimes(1);
      expect(setAgentCapabilities).not.toHaveBeenCalled();
      expect(screen.getByLabelText(/^docker$/i)).not.toBeChecked();
    });

    it('proceeds when the Docker socket confirmation is accepted', async () => {
      const { setAgentCapabilities } = await import('../api/agents');
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

      await renderSettings();

      fireEvent.click(await screen.findByLabelText(/^docker$/i));

      expect(confirmSpy).toHaveBeenCalledTimes(1);
      await waitFor(() => expect(setAgentCapabilities).toHaveBeenCalledTimes(1));
      expect(setAgentCapabilities.mock.calls[0][1].host_telemetry.config).toEqual({
        ...REGISTRY_HOST_CONFIG,
        include_docker: true,
      });
    });

    it('does not ask for confirmation when Docker telemetry is being turned off', async () => {
      const { getAgent, setAgentCapabilities } = await import('../api/agents');
      getAgent.mockResolvedValue({
        data: {
          ...apiDefaults.agent,
          capabilities: {
            host_telemetry: { enabled: true, config: { include_docker: true } },
            remote_probe: false,
            local_discovery: false,
          },
        },
      });
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

      await renderSettings();

      const docker = await screen.findByLabelText(/^docker$/i);
      expect(docker).toBeChecked();
      fireEvent.click(docker);

      expect(confirmSpy).not.toHaveBeenCalled();
      await waitFor(() => expect(setAgentCapabilities).toHaveBeenCalledTimes(1));
      expect(setAgentCapabilities.mock.calls[0][1].host_telemetry.config.include_docker).toBe(
        false
      );
    });
  });

  describe('hardware link prompt', () => {
    it('renders the link prompt alongside a fully populated telemetry section', async () => {
      const { getAgentTelemetry, getAgentsPresence } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });
      getAgentsPresence.mockResolvedValue({
        data: [
          {
            agent_id: 3,
            online: true,
            connected_since: '2026-08-04T10:00:00Z',
            last_seen_at: '2026-08-04T10:05:00Z',
            capabilities: {},
            hardware: null,
          },
        ],
      });

      renderDetail();
      await openTab('Telemetry');

      expect(await screen.findByText(/Link this agent to Hardware/)).toBeInTheDocument();
      // The prompt must not replace the telemetry — issue 2's "unlinked agent
      // shows nothing" symptom.
      expect(cardValue('CPU')).toBe('12.5%');
      expect(screen.getByText(/Last sample/)).toBeInTheDocument();
      await openTab('Overview');
      expect(screen.getByText('No hardware linked')).toBeInTheDocument();
    });

    it('hides the link prompt once hardware is linked', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });

      renderDetail();
      await openTab('Telemetry');

      await findCards();
      expect(screen.queryByText(/Link this agent to Hardware/)).not.toBeInTheDocument();
      await openTab('Overview');
      expect(screen.getByText(/lab-nas/)).toBeInTheDocument();
    });
  });
});
