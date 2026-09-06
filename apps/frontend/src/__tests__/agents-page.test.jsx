import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentsPage from '../pages/AgentsPage';

vi.mock('../api/agents', async () => {
  const actual = await vi.importActual('../api/agents');
  return {
    listAgents: vi.fn(() =>
      Promise.resolve({
        data: [
          {
            id: 1,
            status: 'pending',
            hostname: 'box1',
            fingerprint: 'a'.repeat(32),
            os: 'linux',
            arch: 'amd64',
          },
          {
            id: 2,
            status: 'active',
            hostname: 'box2',
            fingerprint: 'b'.repeat(32),
            os: 'linux',
            arch: 'amd64',
            agent_version: '0.1.0',
          },
        ],
      })
    ),
    getAgentsPresence: vi.fn(() => Promise.resolve({ data: [] })),
    // The fleet redesign's second metric read (design §1.2). It has its own
    // 120s cadence inside useFleetMetrics, so it has to exist on the mock even
    // for the tests that only care about presence — an undefined export throws
    // out of the hook's mount effect and takes the whole page down with it.
    getAgentsMetricsSeries: vi.fn(() => Promise.resolve({ data: [] })),
    getInstallCommand: vi.fn(() =>
      Promise.resolve({
        data: { tls_mode: 'self_signed', command: 'curl ...', script_sha256: 'x' },
      })
    ),
    lookupPairingCode: vi.fn(),
    revokeAgent: vi.fn(),
    deleteAgent: vi.fn(),
    getAgent: vi.fn(),
    approveAgent: vi.fn(),
    // AddAgentPanel's inline approve step reads the server's capability
    // defaults and can reject from the panel; both are part of this module's
    // surface now that enrollment finishes on this page.
    getCapabilityDefaults: vi.fn(() => Promise.resolve({ data: {} })),
    rejectAgent: vi.fn(),
    // The REAL implementation, pulled through importActual rather than
    // re-implemented here: Task 15 makes every REST response emit
    // {enabled, config}, and normalizeCapability is what keeps AgentsPage from
    // reading an always-truthy grant object as "granted". A hand-written copy
    // would keep passing after the real normalizer's semantics changed, which
    // is precisely the drift this test exists to catch.
    normalizeCapability: actual.normalizeCapability,
  };
});

// Vitest requires vi.hoisted() for values referenced from inside a vi.mock
// factory. useAgentLive is backed by a plain vi.fn() so each test can drive
// a fresh `statuses` Map/`connected` value across re-renders (unlike the
// real hook, no live WebSocket is involved here — see agent-live-stream.
// test.jsx for that).
const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../components/agents/ServerKeyRotationPanel', () => ({
  default: () => <div data-testid="server-key-rotation-panel" />,
}));

const mockAuthUser = vi.hoisted(() => ({ value: { role: 'admin' } }));
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockAuthUser.value }),
}));

import { getAgent, getAgentsPresence, getInstallCommand, listAgents } from '../api/agents';

describe('AgentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
  });

  // The redesign replaced the floating pending banner with a pinned row at the
  // top of the same dense list, so this now asserts the ordering rather than a
  // separate section: the pending agent is the FIRST row in the table body,
  // above the active fleet, and it carries the review affordance.
  it('pins pending agents to the top of the fleet list, above the active fleet', async () => {
    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument());

    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row');
    // rows[0] is the header row; rows[1] is the first body row.
    const firstBodyRow = rows[1];
    expect(firstBodyRow).toHaveAttribute('data-state', 'pending');
    expect(within(firstBodyRow).getByText(/box1/i)).toBeInTheDocument();
    expect(within(firstBodyRow).getByText(/Waiting for approval/i)).toBeInTheDocument();
    expect(within(firstBodyRow).getByText('Review')).toBeInTheDocument();

    // …and the active agent is still rendered, below it.
    expect(screen.getAllByText(/box2/i).length).toBeGreaterThan(0);
    expect(within(rows[2]).getByText(/box2/i)).toBeInTheDocument();
  });

  it('renders online state, capabilities, and hardware from the bulk presence endpoint', async () => {
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 2,
          online: true,
          connected_since: '2026-08-04T10:00:00Z',
          last_seen_at: '2026-08-04T10:05:00Z',
          capabilities: {
            host_telemetry: { enabled: true, config: { interval_s: 30 } },
            remote_probe: { enabled: false, config: {} },
            local_discovery: { enabled: false, config: {} },
          },
          hardware: {
            id: 9,
            name: 'rack-a-switch',
            hostname: null,
            ip_address: null,
            mac_address: null,
          },
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('online')).toBeInTheDocument());
    // Scoped to the table: the Task 15 capability filter's <select> now also
    // renders a "Host telemetry" option, so an unscoped getByText would match
    // both.
    const table = screen.getByRole('table');
    expect(within(table).getByText('Host telemetry')).toBeInTheDocument();
    // Task 15 / D-11: a disabled grant arrives as {enabled: false, config: {}},
    // which is truthy — the row must still report it as not granted.
    expect(within(table).queryByText('Remote probe')).not.toBeInTheDocument();
    expect(within(table).getByText('rack-a-switch')).toBeInTheDocument();
  });

  it('inserts a newly enrolled agent as a pending row without waiting for the poll', async () => {
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    getAgent.mockResolvedValue({
      data: {
        id: 99,
        status: 'pending',
        hostname: 'freshbox',
        fingerprint: 'c'.repeat(32),
        os: 'linux',
        arch: 'amd64',
      },
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText(/box1/i)).toBeInTheDocument());
    expect(screen.queryByText(/freshbox/i)).not.toBeInTheDocument();

    // Simulate the live "enrolled" stream event (Task 10) — no poll tick.
    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[99, { event_type: 'enrolled', detail: null, ts: Date.now() }]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(getAgent).toHaveBeenCalledWith(99));
    await waitFor(() => expect(screen.getByText(/freshbox/i)).toBeInTheDocument());
  });

  it('toggles rendered online state on connected/disconnected events', async () => {
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 2,
          online: false,
          connected_since: null,
          last_seen_at: null,
          capabilities: {},
          hardware: null,
        },
      ],
    });
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());

    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[2, { event_type: 'connected', detail: null, ts: Date.now() }]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('online')).toBeInTheDocument());

    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[2, { event_type: 'disconnected', detail: null, ts: Date.now() }]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());
  });

  it('lets a fresher presence poll win over a stale cached live event (missed disconnected during a reconnect gap)', async () => {
    // Simulate the exact reported scenario: the agent connected, the WS
    // dropped, and the disconnected event never made it through the
    // reconnect gap — the live map is still pinned to a 'connected' entry
    // captured before the presence poll below resolves.
    const staleConnectedTs = Date.now();
    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[2, { event_type: 'connected', detail: null, ts: staleConnectedTs }]]),
      connected: true,
    });

    // The bulk presence poll (Task 12) lands after that stale event, and
    // says the agent is actually offline with an updated last_seen_at.
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 2,
          online: false,
          connected_since: null,
          last_seen_at: '2026-08-05T12:00:00Z',
          capabilities: {},
          hardware: null,
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    // The fresher poll data must win — the stale cached 'connected' push
    // must not permanently pin the row to 'online'.
    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());
    expect(screen.queryByText('online')).not.toBeInTheDocument();
  });

  it('still applies a fresh live event ahead of the next poll tick (normal case)', async () => {
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 2,
          online: false,
          connected_since: null,
          last_seen_at: null,
          capabilities: {},
          hardware: null,
        },
      ],
    });
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());

    // A live event arriving after the poll resolved must be applied
    // immediately, without waiting for the next REFRESH_MS poll tick.
    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[2, { event_type: 'connected', detail: null, ts: Date.now() }]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('online')).toBeInTheDocument());
  });
});

// Task 15: status / capability / online filters, plus verifying pending rows
// stay pinned at the top of the (now filterable) fleet table under every
// combination.
describe('AgentsPage fleet filters', () => {
  const FLEET = [
    {
      id: 1,
      status: 'pending',
      hostname: 'pending-host',
      fingerprint: 'p'.repeat(32),
      os: 'linux',
      arch: 'amd64',
    },
    {
      id: 2,
      status: 'active',
      name: 'Telemetry Agent',
      hostname: 'telemetry-host',
      fingerprint: 'a'.repeat(32),
      os: 'linux',
      arch: 'amd64',
      agent_version: '0.1.0',
    },
    {
      id: 3,
      status: 'active',
      name: 'Probe Agent',
      hostname: 'probe-host',
      fingerprint: 'b'.repeat(32),
      os: 'linux',
      arch: 'amd64',
      agent_version: '0.1.0',
    },
    {
      id: 4,
      status: 'revoked',
      name: 'Revoked Agent',
      hostname: 'revoked-host',
      fingerprint: 'c'.repeat(32),
      os: 'linux',
      arch: 'amd64',
      agent_version: '0.1.0',
    },
    {
      id: 5,
      status: 'rejected',
      name: 'Rejected Agent',
      hostname: 'rejected-host',
      fingerprint: 'd'.repeat(32),
      os: 'linux',
      arch: 'amd64',
      agent_version: '0.1.0',
    },
  ];

  const PRESENCE = [
    {
      agent_id: 2,
      online: true,
      connected_since: '2026-08-05T10:00:00Z',
      last_seen_at: '2026-08-05T10:00:00Z',
      capabilities: {
        host_telemetry: { enabled: true, config: { interval_s: 30 } },
        remote_probe: { enabled: false, config: {} },
        local_discovery: { enabled: false, config: {} },
      },
      hardware: null,
    },
    {
      agent_id: 3,
      online: false,
      connected_since: null,
      last_seen_at: '2026-08-04T10:00:00Z',
      capabilities: {
        host_telemetry: { enabled: false, config: {} },
        remote_probe: { enabled: true, config: {} },
        local_discovery: { enabled: false, config: {} },
      },
      hardware: null,
    },
    // agent 4 (revoked) and agent 5 (rejected) have no presence entry, so
    // `online` stays null/unknown for them — neither the "online" nor
    // "offline" filter option should match an unknown row.
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    listAgents.mockResolvedValue({ data: FLEET });
    getAgentsPresence.mockResolvedValue({ data: PRESENCE });
  });

  async function renderPage() {
    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByText('Telemetry Agent')).toBeInTheDocument());
  }

  it('frames the filters and their counts as one named region', async () => {
    // The chrome down the left of this page is a stack of unlabelled boxes to
    // anyone navigating by region. The counts belong inside the same box as
    // the controls that produce them: every number in them comes from the
    // predicate these selects set.
    await renderPage();

    const filters = screen.getByRole('region', { name: 'Filters' });
    expect(within(filters).getByLabelText('Status')).toBeInTheDocument();
    expect(within(filters).getByRole('status')).toHaveTextContent(/of \d+ agents/);
  });

  it('narrows the table to the selected status, leaving the pending row pinned', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'revoked' } });

    await waitFor(() => expect(screen.getByText('Revoked Agent')).toBeInTheDocument());
    expect(screen.queryByText('Telemetry Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Probe Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Rejected Agent')).not.toBeInTheDocument();

    // Pending rows are pinned to the top of the same list and are never
    // subject to the filters — an inbox must not be filterable away.
    expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument();
    expect(screen.getByText(/pending-host/i)).toBeInTheDocument();
  });

  it('narrows the table to the selected capability', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'remote_probe' } });

    await waitFor(() => expect(screen.getByText('Probe Agent')).toBeInTheDocument());
    expect(screen.queryByText('Telemetry Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Revoked Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Rejected Agent')).not.toBeInTheDocument();

    expect(screen.getByText(/pending-host/i)).toBeInTheDocument();
  });

  it('narrows the table to the selected online state', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Online'), { target: { value: 'online' } });

    await waitFor(() => expect(screen.getByText('Telemetry Agent')).toBeInTheDocument());
    expect(screen.queryByText('Probe Agent')).not.toBeInTheDocument(); // reported offline
    expect(screen.queryByText('Revoked Agent')).not.toBeInTheDocument(); // unknown (no presence)
    expect(screen.queryByText('Rejected Agent')).not.toBeInTheDocument(); // unknown (no presence)

    expect(screen.getByText(/pending-host/i)).toBeInTheDocument();
  });

  it('applies status, capability, and online filters together while the pending row stays pinned', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'active' } });
    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'host_telemetry' } });
    fireEvent.change(screen.getByLabelText('Online'), { target: { value: 'online' } });

    await waitFor(() => expect(screen.getByText('Telemetry Agent')).toBeInTheDocument());
    expect(screen.queryByText('Probe Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Revoked Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Rejected Agent')).not.toBeInTheDocument();

    // All three filters active at once must still leave the pending row pinned
    // at the top of the list, untouched by any of them.
    expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument();
    expect(screen.getByText(/pending-host/i)).toBeInTheDocument();
  });

  it('shows an empty-state row when no fleet rows match, without hiding the pinned pending row', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'active' } });
    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'local_discovery' } });

    await waitFor(() =>
      expect(screen.getByText('No agents match the current filters.')).toBeInTheDocument()
    );
    expect(screen.getByText(/pending-host/i)).toBeInTheDocument();
  });
});

// Design §4's two states that used to have no rendering at all: an empty fleet
// (which showed an empty 11-column table) and a failed presence poll (which
// AgentsPage swallowed with `.catch(() => {})`, freezing every metric while the
// page still looked live).
describe('AgentsPage degraded states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
  });

  it('makes the add-agent panel the whole page when there are no agents at all', async () => {
    listAgents.mockResolvedValue({ data: [] });
    getAgentsPresence.mockResolvedValue({ data: [] });

    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    // Expanded without being asked, and fetching the command on mount.
    await waitFor(() => expect(getInstallCommand).toHaveBeenCalled());
    expect(screen.getByText('Add an agent')).toBeInTheDocument();
    // Named, like the other chrome on this page. It keeps its own section
    // rather than becoming a Panel: standalone it *is* the page, and a panel
    // head above its numbered steps would title the page twice.
    expect(screen.getByRole('region', { name: 'Add an agent' })).toBeInTheDocument();
    // No table chrome and no filters — there is nothing to sort or filter.
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Status')).not.toBeInTheDocument();
  });

  it('keeps the last good metric values and marks them stale when a presence poll fails', async () => {
    vi.useFakeTimers();
    try {
      listAgents.mockResolvedValue({
        data: [{ id: 2, status: 'active', hostname: 'box2', agent_version: '0.1.0' }],
      });
      // One good poll, then the endpoint starts failing.
      getAgentsPresence
        .mockResolvedValueOnce({
          data: [
            {
              agent_id: 2,
              online: true,
              connected_since: '2026-08-14T10:00:00Z',
              last_seen_at: '2026-08-14T10:00:00Z',
              capabilities: {},
              hardware: null,
              latest: { collected_at: '2026-08-14T10:00:00Z', cpu_pct: 81 },
            },
          ],
        })
        .mockRejectedValue(new Error('presence down'));

      render(
        <MemoryRouter initialEntries={['/agents']}>
          <AgentsPage />
        </MemoryRouter>
      );

      await vi.advanceTimersByTimeAsync(0);
      expect(screen.getByText('81%')).toBeInTheDocument();
      expect(screen.getByRole('table')).not.toHaveAttribute('data-stale');

      // One full presence tick later the poll has failed.
      await vi.advanceTimersByTimeAsync(30_000);

      // The value is kept — blanking it would be worse than showing it old —
      // but the table is flagged stale so CSS dims it, and the note says how
      // old "old" is.
      expect(screen.getByText('81%')).toBeInTheDocument();
      expect(screen.getByRole('table')).toHaveAttribute('data-stale', 'true');
      expect(screen.getByText(/Last updated/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

// Design §3's invariant, stated there as a rule the whole three-clock
// arrangement rests on: "a WS push never overrides a metric value". The three
// sources have deliberately disjoint slices — the stream owns presence
// transitions, the 30s poll owns the head values, the 120s series owns the
// sparkline shape — so nothing has to arbitrate between two sources claiming
// the same number. The regression this guards against is a one-character one:
// `{...row, ...push}` instead of writing the single key the push is allowed to
// own, which would let a stream frame silently rewrite a measurement.
describe('AgentsPage live merge invariant', () => {
  const POLLED_CPU_PCT = 81;
  // A push shaped like the thing it must not be allowed to write. The real
  // stream frame carries none of these fields — that is the point: if the merge
  // ever spreads the push wholesale, this is what the row would start printing.
  const impostorPush = (eventType) => ({
    event_type: eventType,
    detail: null,
    // Strictly newer than presenceFetchedAt, which isLivePushFresh compares
    // with `<=` — a push landing in the same millisecond as the poll loses.
    ts: Date.now() + 1,
    cpu_pct: 5,
    latest: { collected_at: '2026-08-14T10:01:00Z', cpu_pct: 5 },
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    listAgents.mockResolvedValue({
      data: [{ id: 2, status: 'active', hostname: 'box2', agent_version: '0.1.0' }],
    });
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 2,
          online: false,
          connected_since: null,
          last_seen_at: '2026-08-14T10:00:00Z',
          capabilities: {},
          hardware: null,
          latest: { collected_at: '2026-08-14T10:00:00Z', cpu_pct: POLLED_CPU_PCT },
        },
      ],
    });
  });

  const renderPage = () =>
    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

  it('lets a connected push move the dot while the value stays the polled one', async () => {
    const { rerender } = renderPage();

    // Offline: the metric columns collapse, so nothing is claiming a reading.
    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());
    expect(screen.queryByText(`${POLLED_CPU_PCT}%`)).not.toBeInTheDocument();

    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[2, impostorPush('connected')]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    // The push flipped presence — that slice is its to own — and the number
    // that appeared with it came from the poll, not from the frame that
    // happened to be carrying one.
    await waitFor(() => expect(screen.getByText('online')).toBeInTheDocument());
    expect(screen.getByText(`${POLLED_CPU_PCT}%`)).toBeInTheDocument();
    expect(screen.queryByText('5%')).not.toBeInTheDocument();
  });

  it('lets a revoked push move the status while the value stays the polled one', async () => {
    getAgentsPresence.mockResolvedValue({
      data: [
        {
          agent_id: 2,
          online: true,
          connected_since: '2026-08-14T09:00:00Z',
          last_seen_at: '2026-08-14T10:00:00Z',
          capabilities: {},
          hardware: null,
          latest: { collected_at: '2026-08-14T10:00:00Z', cpu_pct: POLLED_CPU_PCT },
        },
      ],
    });
    const { rerender } = renderPage();
    await waitFor(() => expect(screen.getByText(`${POLLED_CPU_PCT}%`)).toBeInTheDocument());

    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[2, impostorPush('revoked')]]),
      connected: true,
    });
    rerender(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    // `status` is the other key a push may write. Everything else on the row —
    // including the head value it was carrying — is still the poll's.
    await waitFor(() => expect(screen.getByText('revoked')).toBeInTheDocument());
    expect(screen.getByText(`${POLLED_CPU_PCT}%`)).toBeInTheDocument();
    expect(screen.queryByText('5%')).not.toBeInTheDocument();
  });

  it('ignores a push that the poll has already overtaken, metrics included', async () => {
    // The stale-push guard and the metric invariant meet here: a push older
    // than the last successful poll loses outright, so it can move neither the
    // dot nor — under any regression — the number beside it.
    mockUseAgentLive.mockReturnValue({
      statuses: new Map([[2, { ...impostorPush('connected'), ts: Date.now() - 60_000 }]]),
      connected: true,
    });

    renderPage();

    await waitFor(() => expect(screen.getByText('offline')).toBeInTheDocument());
    expect(screen.queryByText('online')).not.toBeInTheDocument();
    expect(screen.queryByText('5%')).not.toBeInTheDocument();
  });
});

describe('AgentsPage install command errors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
  });

  it('shows what the server said went wrong instead of a generic failure', async () => {
    // The backend answers 503 with an operator-fixable reason (an unreadable
    // TLS cert, say). Swallowing it left "Add agent" failing with nothing to
    // act on and the only explanation buried in journalctl.
    getInstallCommand.mockRejectedValueOnce({
      response: {
        status: 503,
        data: { detail: 'The TLS certificate at /x/y.pem is not readable' },
      },
    });

    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByText('Add agent')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Add agent'));

    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(expect.stringContaining('not readable'))
    );
  });

  it('falls back to a generic message when the server offers no detail', async () => {
    getInstallCommand.mockRejectedValueOnce(new Error('network down'));

    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByText('Add agent')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Add agent'));

    await waitFor(() =>
      // AGT-15: the fallback still has to be actionable, so it names what to
      // check rather than only reporting that something went wrong.
      expect(mockToast.error).toHaveBeenCalledWith(
        expect.stringContaining('Could not generate an install command')
      )
    );
  });
});

it('shows the server-key rotation panel to an admin', async () => {
  render(
    <MemoryRouter initialEntries={['/agents']}>
      <AgentsPage />
    </MemoryRouter>
  );
  await waitFor(() => expect(screen.getByTestId('server-key-rotation-panel')).toBeInTheDocument());
});

it('hides the server-key rotation panel from a non-admin', async () => {
  mockAuthUser.value = { role: 'viewer' };
  render(
    <MemoryRouter initialEntries={['/agents']}>
      <AgentsPage />
    </MemoryRouter>
  );
  await waitFor(() => expect(screen.getByRole('heading', { name: /agents/i })).toBeInTheDocument());
  expect(screen.queryByTestId('server-key-rotation-panel')).not.toBeInTheDocument();
  mockAuthUser.value = { role: 'admin' };
});
