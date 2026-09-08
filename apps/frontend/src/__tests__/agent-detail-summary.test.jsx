import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import {
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
    // vi.restoreAllMocks() undoes any vi.spyOn() stubs from this file's own
    // tests. This file has none today; it is kept here, as it was in the
    // original single-file suite, for parity with agent-detail-capabilities.test.jsx,
    // whose window.confirm stub does need it.
    vi.restoreAllMocks();
  });

  describe('summary cards', () => {
    it('renders all eight summary cards with formatMetric output', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });

      renderDetail();
      await openTab('Telemetry');

      await findCards();
      expect(cardValue('CPU')).toBe('12.5%');
      expect(cardValue('Memory')).toBe('63.4%');
      expect(cardValue('Root disk')).toBe('41.2%');
      // The renderings the fleet row uses for the same two metrics. This tile
      // and that row read the same sample from the same host, so a raw
      // "1,234,568 B/s" here beside "↓1.2 MB/s" there was one number in two
      // languages — and 25h is an uptime nobody states that way out loud.
      expect(cardValue('Network receive')).toBe('1.2 MB/s');
      expect(cardValue('Temperature')).toBe('48.5 °C');
      expect(cardValue('Load (1m)')).toBe('1.23');
      expect(cardValue('Uptime')).toBe('1d 1h');
    });

    it('renders a null summary field as Unavailable rather than omitting the card', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });

      renderDetail();
      await openTab('Telemetry');

      // net_tx_bps is null in the fixture; a missing key must behave the same.
      await screen.findByText('Network transmit');
      expect(cardValue('Network transmit')).toBe('Unavailable');
    });

    it('renders every card as Unavailable when the sample carries no summary at all', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({ latest: { summary: null } }),
      });

      renderDetail();
      await openTab('Telemetry');

      await findCards();
      expect(cardValue('CPU')).toBe('Unavailable');
      expect(cardValue('Uptime')).toBe('Unavailable');
    });
  });

  describe('staleness', () => {
    it('renders Live for a sample inside the staleness window', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: { collected_at: new Date(Date.now() - 45_000).toISOString() },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      expect(await screen.findByText(/Last sample/)).toHaveTextContent('Live');
    });

    it('renders Stale for an older sample but keeps the last sample cards populated', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      // 10 minutes old against a 30 s cadence: max(3*30s, 90s) = 90 s.
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: { collected_at: new Date(Date.now() - 600_000).toISOString() },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const status = await screen.findByText(/Last sample/);
      expect(status).toHaveTextContent('Stale');
      expect(status).not.toHaveTextContent('Live');
      // "mark data stale while preserving the last sample" — the cards must
      // not clear.
      expect(cardValue('CPU')).toBe('12.5%');
      expect(cardValue('Memory')).toBe('63.4%');
    });

    it('widens the staleness window for a slow cadence rather than pinning the 90s floor', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      // interval 600 s => max(1_800_000, 90_000) = 30 min, so a 10-minute-old
      // sample is still Live. This is the half of the max() that a literal
      // 90 s threshold would silently break.
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: { collected_at: new Date(Date.now() - 600_000).toISOString() },
          capability: { enabled: true, config: { interval_s: 600 } },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      expect(await screen.findByText(/Last sample/)).toHaveTextContent('Live');
    });

    it('distinguishes a projected sample from an agent-only one', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({ latest: { projected: true } }),
      });

      const { unmount } = renderDetail();
      await openTab('Telemetry');
      expect(await screen.findByText(/Last sample/)).toHaveTextContent(
        'Projected to linked hardware'
      );
      unmount();

      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({ latest: { projected: false } }),
      });
      renderDetail();
      await openTab('Telemetry');
      const status = await screen.findByText(/Last sample/);
      expect(status).toHaveTextContent('Agent only');
      expect(status).not.toHaveTextContent('Projected to linked hardware');
    });
  });

  // Placed last on purpose: it fails if any test above in this file leaked a
  // mockResolvedValue past beforeEach. vi.clearAllMocks() alone does not
  // restore implementations, which is why beforeEach re-applies each one.
  // Every test in this file reassigns getAgentTelemetry, so that is the one
  // fixture this canary checks.
  it('starts every test from the default api fixtures', async () => {
    const api = await import('../api/agents');
    await expect(api.getAgentTelemetry()).resolves.toEqual(await apiDefaults.getAgentTelemetry());
  });
});
