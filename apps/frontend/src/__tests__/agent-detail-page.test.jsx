import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';

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
  getAgentTelemetry: vi.fn(apiDefaults.getAgentTelemetry),
  getAgentTelemetryHistory: vi.fn(apiDefaults.getAgentTelemetryHistory),
  getAgentsPresence: vi.fn(apiDefaults.getAgentsPresence),
  getCapabilityDefaults: vi.fn(apiDefaults.getCapabilityDefaults),
  setAgentCapabilities: vi.fn(apiDefaults.setAgentCapabilities),
  revokeAgent: vi.fn(apiDefaults.revokeAgent),
  triggerAgentUpdate: vi.fn(apiDefaults.triggerAgentUpdate),
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

describe('AgentDetailPage', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    // clearAllMocks does NOT restore implementations; do it explicitly so no
    // test inherits another test's mockResolvedValue.
    const api = await import('../api/agents');
    api.getAgent.mockImplementation(apiDefaults.getAgent);
    api.getAgentEvents.mockImplementation(apiDefaults.getAgentEvents);
    api.getAgentTelemetry.mockImplementation(apiDefaults.getAgentTelemetry);
    api.getAgentTelemetryHistory.mockImplementation(apiDefaults.getAgentTelemetryHistory);
    api.getAgentsPresence.mockImplementation(apiDefaults.getAgentsPresence);
    api.getCapabilityDefaults.mockImplementation(apiDefaults.getCapabilityDefaults);
    api.setAgentCapabilities.mockImplementation(apiDefaults.setAgentCapabilities);
    api.revokeAgent.mockImplementation(apiDefaults.revokeAgent);
    api.triggerAgentUpdate.mockImplementation(apiDefaults.triggerAgentUpdate);
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    mockTelemetryStream.data = new Map();
  });

  afterEach(() => {
    // The capability-editor tests stub window.confirm with vi.spyOn.
    vi.restoreAllMocks();
  });

  it('renders capabilities and the event timeline', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    expect(screen.getByText('approved')).toBeInTheDocument();
  });

  it('renders host-telemetry config toggles the server registry declares but the frontend has no copy of', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    // Only in the server registry — proves HOST_DEFAULTS is really gone.
    const gpu = await screen.findByLabelText(/^gpu$/i);
    expect(gpu).toBeChecked();
    expect(screen.getByLabelText(/^docker$/i)).not.toBeChecked();
  });

  it('falls back to the fetched registry defaults for cadence and unset toggles', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
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

    await waitFor(() => expect(screen.getByText('online')).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());

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

    await waitFor(() => expect(screen.getByText('online')).toBeInTheDocument());

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

    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());
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

    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());
    expect(screen.queryByText('online')).not.toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());

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

    await waitFor(() => expect(screen.getByText('online')).toBeInTheDocument());
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

    const indicator = await screen.findByText(/Catching up/);
    expect(indicator).toHaveTextContent('120 samples buffered');
    expect(indicator).toHaveTextContent('234.4 KB');
    expect(indicator).toHaveAccessibleName(/backlog/i);
  });

  it('renders no catch-up indicator once the backlog has drained', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue(telemetryWithSpool({ depth: 0, bytes: 0 }));

    renderDetail();

    await waitFor(() => expect(screen.getByText(/Last sample/)).toBeInTheDocument());
    expect(screen.queryByText(/Catching up/)).not.toBeInTheDocument();
  });

  it('renders no catch-up indicator for an agent that never reported a spool', async () => {
    const { getAgentTelemetry } = await import('../api/agents');
    getAgentTelemetry.mockResolvedValue(
      telemetryWithSpool({ depth: null, bytes: null, reported_at: null })
    );

    renderDetail();

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

    const alert = await screen.findByRole('alert');
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

    expect(await screen.findByText('Containers')).toBeInTheDocument();
    expect(screen.getByText(/1 of 101 containers running/)).toBeInTheDocument();
    expect(screen.getByText('/web')).toBeInTheDocument();
    expect(screen.getByText('nginx')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/100 containers/);
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

    const alert = await screen.findByRole('alert');
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

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('host.thermal: degraded');
    expect(screen.getByText('12.5%')).toBeInTheDocument();
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

    await waitFor(() =>
      expect(screen.getByText(/No host samples received yet/)).toBeInTheDocument()
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('/proc unreadable');
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

      // The push arrived after the in-flight first request was issued, so it
      // legitimately wins over that response.
      expect(await screen.findByRole('alert')).toHaveTextContent('fault that later cleared');

      // 30 s later the page polls again. That request is issued *after* the
      // cached push arrived, so the poll is strictly fresher and must win.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30000);
      });

      await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
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

  // A summary card is <article><span>{label}</span><strong>{value}</strong>.
  function cardValue(label) {
    const article = screen.getByText(label).closest('article');
    return article.querySelector('strong').textContent;
  }

  describe('summary cards', () => {
    it('renders all eight summary cards with formatMetric output', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });

      renderDetail();

      await screen.findByText('CPU');
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

      await screen.findByText('CPU');
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

      expect(await screen.findByText(/Last sample/)).toHaveTextContent('Live');
    });

    it('distinguishes a projected sample from an agent-only one', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({ latest: { projected: true } }),
      });

      const { unmount } = renderDetail();
      expect(await screen.findByText(/Last sample/)).toHaveTextContent(
        'Projected to linked hardware'
      );
      unmount();

      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({ latest: { projected: false } }),
      });
      renderDetail();
      const status = await screen.findByText(/Last sample/);
      expect(status).toHaveTextContent('Agent only');
      expect(status).not.toHaveTextContent('Projected to linked hardware');
    });
  });

  describe('live sample push', () => {
    it('re-renders the cards from a pushed sample without polling again', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });

      const { rerender } = renderDetail();
      // Let the initial poll land first — the push has to arrive *after* it,
      // exactly as it does in production, or the poll's own resolution would
      // be what put the numbers on screen.
      await waitFor(() => expect(cardValue('CPU')).toBe('12.5%'));

      mockTelemetryStream.data = new Map([
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

      await screen.findByText('CPU');
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

      const alerts = await screen.findAllByRole('alert');
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

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('host.core: degraded partial read');
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

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('host.thermal: unavailable');
      expect(cardValue('CPU')).toBe('12.5%');
    });

    it('renders the section when the response carries no readiness key at all', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      const fixture = telemetryFixture();
      delete fixture.readiness;
      getAgentTelemetry.mockResolvedValue({ data: fixture });

      renderDetail();

      await screen.findByText('CPU');
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  describe('host-telemetry capability editing', () => {
    // The client guard exists to match the agent-side bounds in
    // internal/capability/capability.go:14-17 (MinIntervalSeconds 10,
    // MaxIntervalSeconds 900). These two tests are what stop the pair drifting.
    it.each([
      ['below the minimum', '5'],
      ['above the maximum', '1000'],
    ])('rejects a cadence %s without calling the API', async (_label, value) => {
      const { setAgentCapabilities } = await import('../api/agents');

      renderDetail();

      const cadence = await screen.findByLabelText(/cadence/i);
      fireEvent.change(cadence, { target: { value } });

      expect(mockToast.error).toHaveBeenCalledWith('Cadence must be between 10 and 900 seconds');
      expect(setAgentCapabilities).not.toHaveBeenCalled();
    });

    it('sends the registry-derived config merged with the patch for a valid cadence', async () => {
      const { setAgentCapabilities } = await import('../api/agents');

      renderDetail();

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

      renderDetail();

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

      renderDetail();

      fireEvent.click(await screen.findByLabelText(/^virtual$/i));

      await waitFor(() =>
        expect(mockToast.error).toHaveBeenCalledWith('Could not update telemetry settings')
      );
    });

    it('aborts before any request when the Docker socket confirmation is declined', async () => {
      const { setAgentCapabilities } = await import('../api/agents');
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

      renderDetail();

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

      renderDetail();

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

      renderDetail();

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

      expect(await screen.findByText(/Link this agent to Hardware/)).toBeInTheDocument();
      // The prompt must not replace the telemetry — issue 2's "unlinked agent
      // shows nothing" symptom.
      expect(cardValue('CPU')).toBe('12.5%');
      expect(screen.getByText(/Last sample/)).toBeInTheDocument();
      expect(screen.getByText('No hardware linked')).toBeInTheDocument();
    });

    it('hides the link prompt once hardware is linked', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({ data: telemetryFixture() });

      renderDetail();

      await screen.findByText('CPU');
      expect(screen.queryByText(/Link this agent to Hardware/)).not.toBeInTheDocument();
      expect(screen.getByText(/lab-nas/)).toBeInTheDocument();
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
