import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentsPage from '../pages/AgentsPage';

vi.mock('../api/agents', () => ({
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
    Promise.resolve({ data: { tls_mode: 'self_signed', command: 'curl ...', script_sha256: 'x' } })
  ),
  lookupPairingCode: vi.fn(),
  revokeAgent: vi.fn(),
  deleteAgent: vi.fn(),
  getAgent: vi.fn(),
  approveAgent: vi.fn(),
}));

// Vitest requires vi.hoisted() for values referenced from inside a vi.mock
// factory. useAgentLive is backed by a plain vi.fn() so each test can drive
// a fresh `statuses` Map/`connected` value across re-renders (unlike the
// real hook, no live WebSocket is involved here — see agent-live-stream.
// test.jsx for that).
const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

import { getAgent, getAgentsPresence } from '../api/agents';

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
          capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
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
    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    expect(screen.getByText('rack-a-switch')).toBeInTheDocument();
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
