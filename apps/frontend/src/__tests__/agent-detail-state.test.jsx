import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderDetail, stripDimmed, stateText } from './helpers/agentDetailHarness';

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

  // ── AGT-14: the state section ───────────────────────────────────────────
  //
  // The precedence and the rules themselves are unit-tested against the pure
  // contract (agent-state.test.js). What can only be checked here is that this
  // page feeds that contract the sources the fleet list does not have — the
  // collector readiness table, the configured cadence, and the event stream,
  // which is the ONLY place a dispatched update's outcome is visible because no
  // REST response carries `pending_update_version`.
  describe('agent state', () => {
    it('says an agent that is genuinely fine is online, and nothing more', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: {
          latest: { collected_at: new Date().toISOString(), summary: {}, payload: {} },
          readiness: [],
          capability: { enabled: true, config: { interval_s: 30 } },
        },
      });
      renderDetail();
      // `online` is the only state agentState emits when nothing else holds, so
      // this is also the assertion that the word reaches the page at all.
      await waitFor(() => expect(stateText()).toContain('Online'));
      expect(stripDimmed()).toBe('false');
      expect(stateText()).not.toContain('Stale telemetry');
      expect(stateText()).not.toContain('No samples yet');
    });

    it('gives every state it shows a reason and an operator action', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: {
          latest: null,
          readiness: [
            {
              collector: 'host.docker',
              state: 'unavailable',
              reason: 'no socket',
              remediation: null,
            },
          ],
          capability: { enabled: true, config: { interval_s: 30 } },
        },
      });
      renderDetail();

      await waitFor(() => expect(stateText()).toContain('Capability degraded'));
      const text = stateText();
      // The requirement is a *documented operator action* per state, not a badge.
      // Not "open the agent": this banner renders on the agent's own page,
      // where that instruction has already been followed. It names the tab
      // instead, which is also the right direction from the fleet list.
      expect(text).toContain(
        'What to do: Read the collector\u2019s own reason and remediation on the Telemetry tab.'
      );
      // …and it names which collector, or the operator has nowhere to look.
      expect(text).toContain('host.docker');

      // "every state it shows", not "the primary state". The <dl> this page
      // replaced rendered "What to do: …" for every holding state; only the
      // primary reaches a banner now, so the rest carry theirs on their chip —
      // in the tooltip and in the accessible name, which AgentStateChip builds
      // from one string. This fixture holds two states: capability_degraded is
      // primary, never_reported is secondary and is exactly the one whose
      // remedy used to be reachable only from the <dl>.
      const chips = [...document.querySelectorAll('.fleet-chip[data-state]')];
      expect(chips.length).toBeGreaterThan(0);
      for (const chip of chips) {
        expect(chip.getAttribute('title')).toContain('What to do: ');
        expect(chip.textContent).toContain('What to do: ');
      }
      const neverReported = document.querySelector('.fleet-chip[data-state="never_reported"]');
      expect(neverReported).toBeTruthy();
      expect(neverReported.textContent).toContain(
        'What to do: Give it one cadence interval. If nothing arrives, check collector readiness.'
      );
    });

    it('derives a pending update from the event stream', async () => {
      const { getAgentEvents } = await import('../api/agents');
      getAgentEvents.mockResolvedValue({
        data: [
          {
            id: 2,
            event_type: 'update_queued',
            created_at: new Date().toISOString(),
            detail: { target_version: '0.9.2' },
          },
        ],
      });
      renderDetail();

      await waitFor(() => expect(stateText()).toContain('Update pending'));
      expect(stateText()).toContain('0.9.2');
    });

    it('lets a later terminal event resolve that pending update', async () => {
      const { getAgentEvents } = await import('../api/agents');
      const now = Date.now();
      getAgentEvents.mockResolvedValue({
        data: [
          {
            id: 3,
            event_type: 'update_succeeded',
            created_at: new Date(now).toISOString(),
            detail: { version: '0.9.2' },
          },
          {
            id: 2,
            event_type: 'update_queued',
            created_at: new Date(now - 60_000).toISOString(),
            detail: { target_version: '0.9.2' },
          },
        ],
      });
      renderDetail();

      // The default fixture has telemetry granted and no sample, so the section
      // settles on `never_reported` — the assertion that matters is that the
      // resolved update has stopped claiming to be in flight.
      await waitFor(() => expect(stateText()).toContain('No samples yet'));
      expect(stateText()).not.toContain('Update pending');
      expect(stateText()).not.toContain('Update failed');
    });

    it('keeps the last-seen label once the server clock has been observed', async () => {
      // The caveat is conditional; the label is not. The header's meta row
      // carries the timestamp with no word for it, so dropping "Last seen" with
      // the caveat would leave an elapsed time labelled by nothing.
      mockClockOffsetMs.mockReturnValue(1200);
      renderDetail();
      await waitFor(() => expect(stateText()).toContain('Last seen'));
      expect(stateText()).not.toContain('has not been observed yet');
    });

    it('admits when elapsed times are measured against an unverified browser clock', async () => {
      // No API response in this suite carries a `Date` header (every call is
      // mocked at the module boundary), so the offset is genuinely unmeasured —
      // and the page has to say so rather than presenting "4 minutes ago" as
      // though it had been checked.
      renderDetail();
      await waitFor(() => expect(stateText()).toContain('Last seen'));
      expect(stateText()).toContain('has not been observed yet');
    });
  });

  // Placed last on purpose: it fails if any test above in this file leaked a
  // mockResolvedValue past beforeEach. vi.clearAllMocks() alone does not
  // restore implementations, which is why beforeEach re-applies each one.
  // This file's own tests reassign getAgentTelemetry, getAgentEvents and
  // mockClockOffsetMs (the "keeps the last-seen label" test pins it to
  // 1200), so those are exactly the fixtures this canary checks.
  it('starts every test from the default api fixtures', async () => {
    const api = await import('../api/agents');
    await expect(api.getAgentTelemetry()).resolves.toEqual(await apiDefaults.getAgentTelemetry());
    await expect(api.getAgentEvents()).resolves.toEqual(await apiDefaults.getAgentEvents());
    expect(mockClockOffsetMs()).toBeNull();
  });
});
