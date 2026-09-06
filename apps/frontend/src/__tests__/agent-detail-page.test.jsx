import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';
import { POLL_BACKOFF_MS } from '../hooks/useAgentDetail';

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

// The registry config the page must fall back to when a grant carries no
// config of its own — the same object the fetched defaults above declare.
const REGISTRY_HOST_CONFIG = {
  interval_s: 45,
  include_filesystems: true,
  include_disks: true,
  include_network: true,
  include_temperatures: true,
  include_virtual: false,
  include_docker: false,
  include_gpu: true,
};

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

function detailTree() {
  return (
    <MemoryRouter initialEntries={['/agents/3']}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderDetail() {
  return render(detailTree());
}

/**
 * Task 14: a section is only in the DOM while its tab is selected, so every
 * assertion about probes, discovery, telemetry or events has to ask for that
 * section first. `fireEvent` rather than `userEvent` on purpose — two tests
 * below drive the poll with fake timers, and userEvent's own timer advance
 * does not compose with them.
 */
async function openTab(name) {
  fireEvent.click(await screen.findByRole('tab', { name }));
  return screen.findByRole('tabpanel');
}

/**
 * What the page says about the agent's state. The old <section aria-label="Agent
 * state"> held a chip row and a <dl> together; Task 14 splits the same wording
 * across the primary state's banner, the secondary states' header chips, and
 * the unverified-clock note, so the assertions that read one element read all
 * three.
 */
/**
 * How the header renders presence now: `composeAgentPage` dims the live strip
 * for an offline agent and leaves it lit for a connected one.
 */
const stripDimmed = () => document.querySelector('.agent-strip')?.getAttribute('data-dimmed');

function stateText() {
  return [
    document.querySelector('.cb-detail-head__chips'),
    document.querySelector('.cb-banner'),
    document.querySelector('.agent-detail-page__last-seen'),
  ]
    .map((element) => element?.textContent ?? '')
    .join(' ');
}

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

  it('renders capabilities and the event timeline', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    // AGT-15: the timeline renders the operator-facing label, not the raw
    // `agent_events.event_type` wire string it used to print verbatim.
    await openTab('Events');
    expect(screen.getByText('Approved')).toBeInTheDocument();
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
  // ── Task 16 / D-12: the spool catch-up indicator ──────────────────────────

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
    getAgentTelemetry.mockResolvedValue(telemetryWithSpool({ depth: 120, bytes: 240000 }));

    renderDetail();
    await openTab('Telemetry');

    const indicator = await screen.findByText(/Catching up/);
    expect(indicator).toHaveTextContent('120 samples buffered');
    expect(indicator).toHaveTextContent('234.4 KB');
    expect(indicator).toHaveAccessibleName(/backlog/i);
  });

  it('renders no catch-up indicator once the backlog has drained', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue(telemetryWithSpool({ depth: 0, bytes: 0 }));

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
      data: { latest: null, readiness: [], spool: { depth: 42, bytes: 1024 } },
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

  // ── Task 19: the telemetry section, end to end ────────────────────────────
  //
  // Shape mirrors GET /api/v1/agents/{id}/telemetry (api/agents.py:288-303)
  // plus Task 16's `spool` key. `latest` is merged shallowly so a test can
  // override one field without restating the whole sample; passing
  // `latest: null` clears it outright.
  function telemetryFixture({ latest, ...rest } = {}) {
    const base = {
      latest: {
        sample_id: '11111111-1111-4111-8111-111111111111',
        collected_at: new Date().toISOString(),
        status: 'ok',
        projected: true,
        summary: {
          cpu_pct: 12.5,
          mem_pct: 63.4,
          root_disk_pct: 41.2,
          net_rx_bps: 1234567.8,
          net_tx_bps: null,
          max_temp_c: 48.5,
          load_1: 1.234,
          uptime_s: 90061,
        },
        payload: {},
      },
      readiness: [],
      capability: { enabled: true, config: { interval_s: 30 } },
      hardware_id: 5,
      spool: { depth: 0, bytes: 0, reported_at: null },
    };
    return {
      ...base,
      ...rest,
      latest: latest === null ? null : { ...base.latest, ...latest },
    };
  }

  /**
   * The Telemetry tab's own section. Task 14 put a live strip in the sticky
   * header that repeats CPU/MEM/DISK/NET/TEMP and their formatted values, so
   * an unscoped getByText('CPU') now matches two elements. Every assertion
   * about the cards is scoped here; the strip has its own suite
   * (agent-live-strip.test.jsx).
   */
  const telemetrySection = () => screen.getByRole('region', { name: 'Host telemetry' });

  /** Waits for the summary cards to render, then returns the section. */
  const findCards = () =>
    waitFor(() => {
      within(telemetrySection()).getByText('CPU');
      return telemetrySection();
    });

  // Task 16: a summary card is a StatTile — <div class="cb-tile"> with its
  // label and value in their own elements — rather than the bare
  // <article><span><strong> the page used to emit.
  function cardValue(label) {
    const tile = within(telemetrySection()).getByText(label).closest('.cb-tile');
    return tile.querySelector('.cb-tile__value').textContent;
  }

  /**
   * The readiness and truncation callouts on the Telemetry tab.
   *
   * Task 16 renders these as Banners, which are role="status" and not
   * role="alert" — every one of these conditions is already true when the tab
   * opens, and an alert would interrupt a screen reader on each navigation.
   * Scoped to the tab body because the page header carries a Banner of its own
   * for the primary agent state.
   */
  const telemetryBanners = () => within(telemetrySection()).queryAllByRole('status');

  const findTelemetryBanners = async () => {
    await waitFor(() => expect(telemetryBanners().length).toBeGreaterThan(0));
    return telemetryBanners();
  };

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
      expect(cardValue('Network receive')).toBe('1,234,568 B/s');
      expect(cardValue('Temperature')).toBe('48.5 °C');
      expect(cardValue('Load (1m)')).toBe('1.23');
      expect(cardValue('Uptime')).toBe('25h');
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

  describe('device tables', () => {
    it('derives one header cell per key of the first row and one row per entry', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              filesystems: [
                { device: '/dev/sda1', mountpoint: '/', used_pct: 41.2 },
                { device: '/dev/sdb1', mountpoint: '/var', used_pct: 12 },
              ],
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const table = (await screen.findByText('Filesystems')).closest('.agent-telemetry__table');
      const headers = within(table)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent);
      expect(headers).toEqual(['device', 'mountpoint', 'used pct']);
      // getAllByRole('row') includes the header row.
      expect(within(table).getAllByRole('row')).toHaveLength(3);
      expect(within(table).getByText('/var')).toBeInTheDocument();
    });

    it('renders nothing for an empty or absent device array', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              // present but empty
              disks: [],
              // absent entirely: filesystems, interfaces, temperatures
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      await findCards();
      expect(screen.queryByText('Disks')).not.toBeInTheDocument();
      expect(screen.queryByText('Filesystems')).not.toBeInTheDocument();
      expect(screen.queryByText('Interfaces')).not.toBeInTheDocument();
      expect(screen.queryByText('Temperatures')).not.toBeInTheDocument();
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('renders the interface and temperature tables from their own payload arrays', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              interfaces: [{ name: 'eth0', rx_bps: 1000, tx_bps: 2000 }],
              temperatures: [
                { sensor: 'coretemp', celsius: 48.5 },
                { sensor: 'nvme', celsius: 33 },
              ],
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const interfaces = (await screen.findByText('Interfaces')).closest('.agent-telemetry__table');
      expect(within(interfaces).getAllByRole('row')).toHaveLength(2);
      expect(within(interfaces).getByText('eth0')).toBeInTheDocument();

      const temps = screen.getByText('Temperatures').closest('.agent-telemetry__table');
      expect(
        within(temps)
          .getAllByRole('columnheader')
          .map((cell) => cell.textContent)
      ).toEqual(['sensor', 'celsius']);
      expect(within(temps).getAllByRole('row')).toHaveLength(3);
    });
  });

  describe('readiness', () => {
    it('alerts only on degraded and unavailable collectors', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          readiness: [
            { collector: 'host.core', state: 'ready', reason: null, remediation: null },
            {
              collector: 'host.thermal',
              state: 'degraded',
              reason: 'no thermal zones exposed',
              remediation: 'install lm-sensors',
            },
            {
              collector: 'host.docker',
              state: 'unavailable',
              reason: 'docker socket not readable',
              remediation: 'mount /var/run/docker.sock',
            },
            { collector: 'host.net', state: 'disabled', reason: 'not enabled', remediation: null },
          ],
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const alerts = await findTelemetryBanners();
      expect(alerts).toHaveLength(2);
      expect(alerts[0]).toHaveTextContent('host.thermal: degraded');
      expect(alerts[0]).toHaveTextContent('no thermal zones exposed — install lm-sensors');
      expect(alerts[1]).toHaveTextContent('host.docker: unavailable');
      expect(alerts[1]).toHaveTextContent(
        'docker socket not readable — mount /var/run/docker.sock'
      );
      expect(screen.queryByText(/host\.core/)).not.toBeInTheDocument();
      expect(screen.queryByText(/host\.net/)).not.toBeInTheDocument();
    });

    it('omits the em-dash remediation clause when there is no remediation', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          readiness: [
            {
              collector: 'host.core',
              state: 'degraded',
              reason: 'partial read',
              remediation: null,
            },
          ],
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const [alert] = await findTelemetryBanners();
      // Banner keeps the collector line and the reason in separate elements,
      // so they are asserted separately; what matters is that the em-dash
      // clause is absent when there is nothing to remediate.
      expect(alert).toHaveTextContent('host.core: degraded');
      expect(alert).toHaveTextContent('partial read');
      expect(alert.textContent).not.toContain('—');
    });

    it('renders a partial readiness list — collectors absent entirely — without error', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      // Only one of the host collectors reported; the rest are simply missing,
      // which is the normal shape while a collector has never run.
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          readiness: [{ collector: 'host.thermal', state: 'unavailable' }],
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const [alert] = await findTelemetryBanners();
      expect(alert).toHaveTextContent('host.thermal: unavailable');
      expect(cardValue('CPU')).toBe('12.5%');
    });

    it('renders the section when the response carries no readiness key at all', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      const fixture = telemetryFixture();
      delete fixture.readiness;
      getAgentTelemetry.mockResolvedValue({ data: fixture });

      renderDetail();
      await openTab('Telemetry');

      await findCards();
      expect(telemetryBanners()).toHaveLength(0);
    });
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
      expect(text).toContain('What to do: Open the agent and read the collector');
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

  // Placed last on purpose: it fails if any test above leaked a
  // mockResolvedValue past beforeEach. vi.clearAllMocks() alone does not
  // restore implementations, which is why beforeEach re-applies each one.
  it('starts every test from the default api fixtures', async () => {
    const api = await import('../api/agents');
    await expect(api.getAgentTelemetry('3')).resolves.toEqual({
      data: { latest: null, readiness: [] },
    });
    await expect(api.getAgentTelemetryHistory('3', '1h')).resolves.toEqual({
      data: { points: [] },
    });
    const presence = await api.getAgentsPresence({ ids: ['3'] });
    expect(presence.data[0].hardware).not.toBeNull();
    const defaults = await api.getCapabilityDefaults();
    expect(defaults.data.host_telemetry.config.interval_s).toBe(45);
  });
});
