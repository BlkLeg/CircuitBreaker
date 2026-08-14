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

import { getAgent, getAgentsPresence, getInstallCommand, listAgents } from '../api/agents';

describe('AgentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
  });

  it('pins pending agents to a banner separate from the main table', async () => {
    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument());
    expect(screen.getByText(/box1/i)).toBeInTheDocument();
    expect(screen.getAllByText(/box2/i).length).toBeGreaterThan(0);
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
// stay pinned above the (now filterable) fleet table under every combination.
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

  it('narrows the table to the selected status, leaving the pending row pinned', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'revoked' } });

    await waitFor(() => expect(screen.getByText('Revoked Agent')).toBeInTheDocument());
    expect(screen.queryByText('Telemetry Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Probe Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Rejected Agent')).not.toBeInTheDocument();

    // Pending row stays pinned in its banner regardless of the status filter.
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

    // All three filters active at once must still leave pending pinned above
    // the table, in its own banner, untouched by any of them.
    expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument();
    expect(screen.getByText(/pending-host/i)).toBeInTheDocument();
  });

  it('shows an empty-state row when no fleet rows match, without hiding the pending banner', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'active' } });
    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'local_discovery' } });

    await waitFor(() =>
      expect(screen.getByText('No agents match the current filters.')).toBeInTheDocument()
    );
    expect(screen.getByText(/pending-host/i)).toBeInTheDocument();
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
      expect(mockToast.error).toHaveBeenCalledWith('Could not generate an install command')
    );
  });
});
