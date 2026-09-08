import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { POLL_BACKOFF_MS } from '../hooks/useAgentDetail';
import {
  renderDetail,
  openTab,
  detailTree,
  telemetryFixture,
  telemetrySection,
  telemetryBanners,
  findTelemetryBanners,
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

  // ── Task 18: the capability.readiness broadcast, consumed live ────────────

  // The broadcast carries the *full* readiness list, so a whole-array replace
  // is correct — `disabled` rows stay filtered out of the warning list.
  const READINESS_PUSH = {
    type: 'capability.readiness',
    agent_id: 3,
    readiness: [
      {
        collector: 'host.thermal',
        state: 'degraded',
        reason: 'no thermal zones exposed',
        remediation: 'install lm-sensors',
      },
      { collector: 'host.docker', state: 'disabled', reason: 'not enabled', remediation: null },
    ],
  };

  it('renders a degraded readiness warning pushed over the telemetry stream without waiting for the 30s poll', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    // The polled snapshot is clean; only the push knows about the fault.
    getAgentTelemetry.mockResolvedValue({ data: { latest: null, readiness: [] } });
    mockTelemetryStream.data = new Map([['readiness:agent:3', READINESS_PUSH]]);

    renderDetail();
    await openTab('Telemetry');

    const [alert] = await findTelemetryBanners();
    expect(alert).toHaveTextContent('host.thermal: degraded');
    expect(alert).toHaveTextContent('no thermal zones exposed');
    expect(alert).toHaveTextContent('install lm-sensors');
    expect(screen.queryByText(/host\.docker/)).not.toBeInTheDocument();
    // Proves it came from the push and not from a second poll.
    expect(getAgentTelemetry).toHaveBeenCalledTimes(1);
  });

  it('a live readiness push does not blank the metric cards', async () => {
    // Regression lock for the reason readiness gets its own namespaced key in
    // useTelemetryStream: sharing the sample slot would overwrite
    // `update.payload` and wipe every summary card.
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: {
          collected_at: new Date().toISOString(),
          projected: false,
          summary: { cpu_pct: 12.5 },
        },
        readiness: [],
        capability: { enabled: true, config: { interval_s: 30 } },
      },
    });
    mockTelemetryStream.data = new Map([['readiness:agent:3', READINESS_PUSH]]);

    renderDetail();
    await openTab('Telemetry');

    const [alert] = await findTelemetryBanners();
    expect(alert).toHaveTextContent('host.thermal: degraded');
    expect(within(telemetrySection()).getByText('12.5%')).toBeInTheDocument();
    expect(screen.getByText(/Last sample/)).toBeInTheDocument();
  });

  it('ignores a readiness slot that carries no readiness array', async () => {
    // The polled list must SURVIVE a malformed push. Asserting against an
    // already-empty polled list would pass with the Array.isArray guard
    // deleted too: the effect would write `readiness: undefined`, which the
    // render path swallows via optional chaining, so nothing would move.
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue({
      data: {
        latest: null,
        readiness: [
          {
            collector: 'host.core',
            state: 'unavailable',
            reason: '/proc unreadable',
            remediation: 'verify /proc is mounted',
          },
        ],
      },
    });
    mockTelemetryStream.data = new Map([
      ['readiness:agent:3', { type: 'capability.readiness', agent_id: 3 }],
    ]);

    renderDetail();
    await openTab('Telemetry');

    await waitFor(() =>
      expect(screen.getByText(/No host samples received yet/)).toBeInTheDocument()
    );
    expect((await findTelemetryBanners())[0]).toHaveTextContent('/proc unreadable');
  });

  it('lets a fresher poll override a readiness push cached from before it', async () => {
    // The backend only publishes readiness when it CHANGES (D-4), and
    // useTelemetryStream never clears its data map on a socket drop. So a
    // change occurring while the browser is disconnected is never pushed. If
    // the cached push kept being re-applied on top of every poll, a fault that
    // has since cleared would stay on screen for the life of the page.
    const { getAgentTelemetry } = await import('../api/agents');
    mockTelemetryStream.data = new Map([
      [
        'readiness:agent:3',
        {
          type: 'capability.readiness',
          agent_id: 3,
          readiness: [
            {
              collector: 'host.core',
              state: 'unavailable',
              reason: 'fault that later cleared',
              remediation: 'x',
            },
          ],
        },
      ],
    ]);
    getAgentTelemetry.mockResolvedValue({
      data: { latest: null, readiness: [], spool: null },
    });

    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderDetail();
      await openTab('Telemetry');

      // The push arrived after the in-flight first request was issued, so it
      // legitimately wins over that response.
      expect((await findTelemetryBanners())[0]).toHaveTextContent('fault that later cleared');

      // The next reconciliation poll — at the backoff period, because the
      // stream is delivering — is issued *after* the cached push arrived, so
      // it is strictly fresher and must win.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_BACKOFF_MS);
      });

      await waitFor(() => expect(telemetryBanners()).toHaveLength(0));
    } finally {
      vi.useRealTimers();
    }
  });

  describe('live sample push', () => {
    it('re-renders the cards from a pushed sample without polling again', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });
      // Seeded so useAgentDetail's `streamIsDelivering` is already true at
      // mount. The poll-backoff effect depends on that boolean, and the sample
      // push below must not be the thing that flips it: the resulting
      // dependency change re-fires an immediate poll that lands after the
      // merge and clobbers it (the sample merge has no re-apply-after-poll
      // guard — see agent-detail-hook.test.jsx, which seeds it the same way).
      mockTelemetryStream.data = new Map([['seed:unrelated', {}]]);

      const { rerender } = renderDetail();
      await openTab('Telemetry');
      // Let the initial poll land first — the push has to arrive *after* it,
      // exactly as it does in production, or the poll's own resolution would
      // be what put the numbers on screen.
      await waitFor(() => expect(cardValue('CPU')).toBe('12.5%'));

      mockTelemetryStream.data = new Map([
        ['seed:unrelated', {}],
        [
          'agent:3',
          {
            type: 'telemetry.host',
            agent_id: 3,
            collected_at: new Date().toISOString(),
            payload: { status: 'ok', summary: { cpu_pct: 77.7, mem_pct: 5.5 } },
          },
        ],
      ]);
      rerender(detailTree());

      await waitFor(() => expect(cardValue('CPU')).toBe('77.7%'));
      expect(cardValue('Memory')).toBe('5.5%');
      // The push, not a second GET, is what produced those numbers.
      expect(getAgentTelemetry).toHaveBeenCalledTimes(1);
    });

    it('still refreshes on the 30s poll, so the polling fallback survives stream loss', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });
      vi.useFakeTimers();
      try {
        renderDetail();
        await act(async () => {
          await vi.advanceTimersByTimeAsync(0);
        });
        expect(getAgentTelemetry).toHaveBeenCalledTimes(1);

        await act(async () => {
          await vi.advanceTimersByTimeAsync(30_000);
        });
        expect(getAgentTelemetry).toHaveBeenCalledTimes(2);

        await act(async () => {
          await vi.advanceTimersByTimeAsync(30_000);
        });
        expect(getAgentTelemetry).toHaveBeenCalledTimes(3);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('history', () => {
    function historyPoints(count, metric = 'cpu_pct') {
      return Array.from({ length: count }, (_, index) => ({
        bucket: `2026-08-06T0${index}:00:00Z`,
        summary: { [metric]: index + 1 },
      }));
    }

    it('reloads history exactly once for the newly selected range', async () => {
      const { getAgentTelemetry, getAgentTelemetryHistory } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });
      getAgentTelemetryHistory.mockResolvedValue({ data: { points: historyPoints(3) } });

      renderDetail();
      await openTab('Telemetry');

      expect(await screen.findByText('3 history points')).toBeInTheDocument();
      expect(getAgentTelemetryHistory).toHaveBeenCalledWith('3', '1h');
      getAgentTelemetryHistory.mockClear();

      fireEvent.change(screen.getByLabelText(/History range/i), { target: { value: '24h' } });

      await waitFor(() => expect(getAgentTelemetryHistory).toHaveBeenCalledTimes(1));
      expect(getAgentTelemetryHistory).toHaveBeenCalledWith('3', '24h');
    });

    it('renders 0 history points without throwing when the history request rejects', async () => {
      const { getAgentTelemetry, getAgentTelemetryHistory } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });
      getAgentTelemetryHistory.mockRejectedValue(new Error('500'));

      renderDetail();
      await openTab('Telemetry');

      expect(await screen.findByText('0 history points')).toBeInTheDocument();
      expect(screen.queryByLabelText('CPU history')).not.toBeInTheDocument();
    });

    it('draws a chart only for metrics with at least two finite values', async () => {
      const { getAgentTelemetry, getAgentTelemetryHistory } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });
      getAgentTelemetryHistory.mockResolvedValue({
        data: {
          points: [
            { bucket: 'a', summary: { cpu_pct: 1, mem_pct: 10, max_temp_c: null } },
            { bucket: 'b', summary: { cpu_pct: 2, mem_pct: null, max_temp_c: null } },
            { bucket: 'c', summary: { cpu_pct: 3, mem_pct: null, max_temp_c: null } },
          ],
        },
      });

      renderDetail();
      await openTab('Telemetry');

      expect(await screen.findByLabelText('CPU history')).toBeInTheDocument();
      // One present value is not a line. `null` must count as missing, not as
      // 0 — Number(null) is a finite 0 and used to slip through the guard.
      expect(screen.queryByLabelText('Memory history')).not.toBeInTheDocument();
      // Null in every bucket likewise.
      expect(screen.queryByLabelText('Temperature history')).not.toBeInTheDocument();
      // Key absent from every point.
      expect(screen.queryByLabelText('Disk history')).not.toBeInTheDocument();
    });
  });
});
