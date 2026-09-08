import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import {
  renderDetail,
  openTab,
  telemetryBanners,
  findTelemetryBanners,
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
    // vi.restoreAllMocks() undoes any vi.spyOn() stubs from this file's own
    // tests. This file has none today; it is kept here, as it was in the
    // original single-file suite, for parity with agent-detail-capabilities.test.jsx,
    // whose window.confirm stub does need it.
    vi.restoreAllMocks();
  });

  // ── Task 16 / D-12: the spool catch-up indicator ──────────────────────────

  // A backlog the agent reported seconds ago. The tab renders a live catch-up
  // indicator only for a reading it can still call current — a spool block
  // with no `reported_at` describes an unknown backlog instead, which is a
  // different indicator (see agent-telemetry-tab.test.jsx).
  const FRESHLY_REPORTED = () => new Date(Date.now() - 15_000).toISOString();

  function telemetryWithSpool(spool) {
    return {
      data: {
        latest: {
          collected_at: new Date().toISOString(),
          projected: false,
          summary: { cpu_pct: 12.5 },
        },
        readiness: [],
        capability: { enabled: true, config: { interval_s: 30 } },
        spool,
      },
    };
  }

  it('shows a catch-up indicator while the agent has a spool backlog', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue(
      telemetryWithSpool({ depth: 120, bytes: 240000, reported_at: FRESHLY_REPORTED() })
    );

    renderDetail();
    await openTab('Telemetry');

    const indicator = await screen.findByText(/Catching up/);
    expect(indicator).toHaveTextContent('120 samples buffered');
    expect(indicator).toHaveTextContent('234.4 KB');
    expect(indicator).toHaveAccessibleName(/backlog/i);
  });

  it('renders no catch-up indicator once the backlog has drained', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue(
      telemetryWithSpool({ depth: 0, bytes: 0, reported_at: FRESHLY_REPORTED() })
    );

    renderDetail();
    await openTab('Telemetry');

    await waitFor(() => expect(screen.getByText(/Last sample/)).toBeInTheDocument());
    expect(screen.queryByText(/Catching up/)).not.toBeInTheDocument();
  });

  it('renders no catch-up indicator for an agent that never reported a spool', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue(
      telemetryWithSpool({ depth: null, bytes: null, reported_at: null })
    );

    renderDetail();
    await openTab('Telemetry');

    await waitFor(() => expect(screen.getByText(/Last sample/)).toBeInTheDocument());
    expect(screen.queryByText(/Catching up/)).not.toBeInTheDocument();
  });

  // ── Task 17: gaps that only show up when there is no sample ───────────────

  it('renders readiness warnings for an agent that has never produced a sample', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    // The issue-4 case: /proc is unreadable, so the collector reports
    // readiness and never produces a sample. Nesting the warning inside the
    // `latest` ternary made this exact failure invisible.
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: null,
        readiness: [
          {
            collector: 'host.core',
            state: 'unavailable',
            reason: '/proc unreadable',
            remediation: 'check agent permissions',
          },
          // `disabled` is not a fault and must stay filtered out.
          { collector: 'host.docker', state: 'disabled', reason: 'not enabled', remediation: null },
        ],
      },
    });

    renderDetail();
    await openTab('Telemetry');

    const [alert] = await findTelemetryBanners();
    expect(alert).toHaveTextContent('host.core: unavailable');
    expect(alert).toHaveTextContent('/proc unreadable');
    expect(alert).toHaveTextContent('check agent permissions');
    expect(screen.getByText(/No host samples received yet/)).toBeInTheDocument();
    expect(screen.queryByText(/host\.docker/)).not.toBeInTheDocument();
  });

  it('shows the catch-up indicator for an agent with a backlog but no sample yet', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: null,
        readiness: [],
        spool: { depth: 42, bytes: 1024, reported_at: new Date().toISOString() },
      },
    });

    renderDetail();
    await openTab('Telemetry');

    const indicator = await screen.findByText(/Catching up/);
    expect(indicator).toHaveTextContent('42 samples buffered');
    expect(indicator).toHaveTextContent('1.0 KB');
    expect(screen.getByText(/No host samples received yet/)).toBeInTheDocument();
  });

  it('shows the effective cadence alongside the live/stale state', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: { collected_at: new Date().toISOString(), projected: false, summary: {} },
        readiness: [],
        capability: { enabled: true, config: { interval_s: 60 } },
      },
    });

    renderDetail();
    await openTab('Telemetry');

    const status = await screen.findByText(/Last sample/);
    expect(status).toHaveTextContent('Live');
    expect(status).toHaveTextContent('Cadence 60s');
  });

  it('omits the cadence segment while the capability registry is still loading', async () => {
    // `interval` comes from the fetched registry (Task 14), so before
    // GET /agents/capability-defaults resolves there is no cadence to show.
    // Rendering the label anyway produced a bare "Cadence s".
    const { getAgentTelemetry, getCapabilityDefaults } = await import('../api/agents');
    getCapabilityDefaults.mockReturnValue(new Promise(() => {}));
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: { collected_at: new Date().toISOString(), projected: false, summary: {} },
        readiness: [],
        capability: { enabled: true, config: {} },
      },
    });

    renderDetail();
    await openTab('Telemetry');

    const status = await screen.findByText(/Last sample/);
    expect(status).toHaveTextContent('Live');
    expect(status).not.toHaveTextContent('Cadence');
  });

  it('renders the Docker container table and truncation warning', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: {
          collected_at: new Date().toISOString(),
          projected: false,
          summary: {},
          payload: {
            docker: {
              containers: [
                {
                  id: 'abc',
                  name: '/web',
                  image: 'nginx',
                  state: 'running',
                  status: 'Up 2 days',
                },
              ],
              total: 101,
              running: 1,
              truncated: true,
            },
          },
        },
        readiness: [],
        capability: { enabled: true, config: { interval_s: 30, include_docker: true } },
      },
    });

    renderDetail();
    await openTab('Telemetry');

    expect(await screen.findByText('Containers')).toBeInTheDocument();
    expect(screen.getByText(/1 of 101 containers running/)).toBeInTheDocument();
    expect(screen.getByText('/web')).toBeInTheDocument();
    expect(screen.getByText('nginx')).toBeInTheDocument();
    expect(telemetryBanners()[0]).toHaveTextContent(/100 containers/);
  });

  it('does not render a Docker section when the collector is disabled', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: {
          collected_at: new Date().toISOString(),
          projected: false,
          summary: {},
          payload: { filesystems: [{ mountpoint: '/', used_pct: 41.2 }] },
        },
        readiness: [],
        capability: { enabled: true, config: { interval_s: 30, include_docker: false } },
      },
    });

    renderDetail();
    await openTab('Telemetry');

    expect(await screen.findByText('Filesystems')).toBeInTheDocument();
    expect(screen.queryByText('Docker')).not.toBeInTheDocument();
    expect(screen.queryByText('Containers')).not.toBeInTheDocument();
  });

  // Placed last on purpose: it fails if any test above in this file leaked a
  // mockResolvedValue past beforeEach. vi.clearAllMocks() alone does not
  // restore implementations, which is why beforeEach re-applies each one.
  // This file's own tests reassign getAgentTelemetry repeatedly and, once,
  // getCapabilityDefaults to a promise that never resolves (the "omits the
  // cadence segment" test) — exactly the never-resolving leak the top-level
  // apiDefaults comment warns about — so those are the fixtures this canary
  // checks.
  it('starts every test from the default api fixtures', async () => {
    const api = await import('../api/agents');
    await expect(api.getAgentTelemetry()).resolves.toEqual(await apiDefaults.getAgentTelemetry());
    await expect(api.getCapabilityDefaults()).resolves.toEqual(
      await apiDefaults.getCapabilityDefaults()
    );
  });
});
