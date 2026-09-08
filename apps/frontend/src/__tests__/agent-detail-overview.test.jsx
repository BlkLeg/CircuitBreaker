import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';
import { renderDetail, openTab, stripDimmed, stateText } from './helpers/agentDetailHarness';

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

  it('renders capabilities and the event timeline', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    // AGT-15: the timeline renders the operator-facing label, not the raw
    // `agent_events.event_type` wire string it used to print verbatim.
    await openTab('Events');
    expect(screen.getByText('Approved')).toBeInTheDocument();
  });

  // Slice A: the address the agent actually dialed. Without it, an agent that
  // enrolled through the wrong endpoint is indistinguishable from one that
  // enrolled through the right one until it stops reporting.
  it('names the address the agent enrolled through', async () => {
    const api = await import('../api/agents');
    api.getAgent.mockResolvedValue({
      data: { ...apiDefaults.agent, enrolled_via_endpoint: 'https://cb.example.com' },
    });

    renderDetail();

    expect(await screen.findByText('Enrolled via')).toBeInTheDocument();
    expect(screen.getByText('https://cb.example.com')).toBeInTheDocument();
  });

  it('shows a dash for an agent that enrolled before the address was recorded', async () => {
    const api = await import('../api/agents');
    api.getAgent.mockResolvedValue({
      data: { ...apiDefaults.agent, enrolled_via_endpoint: null },
    });

    renderDetail();

    const term = await screen.findByText('Enrolled via');
    expect(term.nextSibling).toHaveTextContent('—');
  });

  it('renders host-telemetry config toggles the server registry declares but the frontend has no copy of', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    // Task 16 put the host-telemetry settings on the Telemetry tab, where
    // spec §7 places them: they are a form, and overview is a reading.
    await openTab('Telemetry');
    // Only in the server registry — proves HOST_DEFAULTS is really gone.
    const gpu = await screen.findByLabelText(/^gpu$/i);
    expect(gpu).toBeChecked();
    expect(screen.getByLabelText(/^docker$/i)).not.toBeChecked();
  });

  it('falls back to the fetched registry defaults for cadence and unset toggles', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    await openTab('Telemetry');
    // The grant is a bare `true` (no config), so every value shown must come
    // from the fetched defaults — 45, not a hardcoded 30.
    const cadence = await screen.findByLabelText(/cadence/i);
    expect(cadence).toHaveValue(45);
    expect(screen.getByLabelText(/^filesystems$/i)).toBeChecked();
    expect(screen.getByLabelText(/^virtual$/i)).not.toBeChecked();
  });

  it('sends the full registry-derived config when a host-telemetry toggle changes', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    setAgentCapabilities.mockResolvedValue({ data: { id: 3, capabilities: {} } });
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    await openTab('Telemetry');
    fireEvent.click(await screen.findByLabelText(/^virtual$/i));

    await waitFor(() => expect(setAgentCapabilities).toHaveBeenCalled());
    expect(setAgentCapabilities.mock.calls[0][1].host_telemetry.config).toEqual({
      interval_s: 45,
      include_filesystems: true,
      include_disks: true,
      include_network: true,
      include_temperatures: true,
      include_virtual: true,
      include_docker: false,
      include_gpu: true,
    });
  });

  it('renders online state and linked-hardware summary from the bulk presence endpoint', async () => {
    renderDetail();

    // Presence reaches the page rather than merely being fetched: an online
    // agent's live strip is undimmed and the overview says when its socket
    // opened. (The bare "online"/"offline" word the header used to carry is
    // now the freshness pill plus the strip's dim state — Tasks 12 and 13.)
    await waitFor(() => expect(screen.getByText(/Connected since/)).toBeInTheDocument());
    expect(stripDimmed()).toBe('false');
    expect(screen.getByText(/lab-nas/)).toBeInTheDocument();
  });

  it('toggles rendered online state on connected/disconnected events', async () => {
    const { getAgentsPresence } = await import('../api/agents');
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 3,
          online: false,
          connected_since: null,
          last_seen_at: null,
          capabilities: {},
          hardware: null,
        },
      ],
    });

    const { rerender } = renderDetail();
    await waitFor(() => expect(stateText()).toContain('Offline'));

    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[3, { event_type: 'connected', detail: null, ts: Date.now() }]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents/3']}>
        <Routes>
          <Route path="/agents/:id" element={<AgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(stripDimmed()).toBe('false'));

    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[3, { event_type: 'disconnected', detail: null, ts: Date.now() }]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents/3']}>
        <Routes>
          <Route path="/agents/:id" element={<AgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(stateText()).toContain('Offline'));
  });

  it('lets a fresher presence poll win over a stale cached live event (missed disconnected during a reconnect gap)', async () => {
    const { getAgentsPresence } = await import('../api/agents');

    // The live map is still pinned to a 'connected' entry captured before
    // the presence poll below resolves — simulating a disconnected event
    // that never arrived during a WS reconnect gap.
    const staleConnectedTs = Date.now();
    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[3, { event_type: 'connected', detail: null, ts: staleConnectedTs }]]),
      connected: true,
    });

    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 3,
          online: false,
          connected_since: null,
          last_seen_at: '2026-08-05T12:00:00Z',
          capabilities: {},
          hardware: null,
        },
      ],
    });

    renderDetail();

    await waitFor(() => expect(stateText()).toContain('Offline'));
    expect(stateText()).not.toContain('Online');
  });

  it('still applies a fresh live event ahead of the next poll (normal case)', async () => {
    const { getAgentsPresence } = await import('../api/agents');
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 3,
          online: false,
          connected_since: null,
          last_seen_at: null,
          capabilities: {},
          hardware: null,
        },
      ],
    });

    const { rerender } = renderDetail();
    await waitFor(() => expect(stateText()).toContain('Offline'));

    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[3, { event_type: 'connected', detail: null, ts: Date.now() }]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents/3']}>
        <Routes>
          <Route path="/agents/:id" element={<AgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(stripDimmed()).toBe('false'));
  });
});
