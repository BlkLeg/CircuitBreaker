import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';

vi.mock('../api/agents', () => ({
  normalizeCapability: (value) =>
    typeof value === 'boolean'
      ? { enabled: value, config: {} }
      : { enabled: Boolean(value?.enabled), config: value?.config ?? {} },
  getAgent: vi.fn(() =>
    Promise.resolve({
      data: {
        id: 3,
        name: null,
        hostname: 'box1',
        status: 'active',
        fingerprint: 'a'.repeat(32),
        agent_version: '0.1.0',
        capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
      },
    })
  ),
  getAgentEvents: vi.fn(() =>
    Promise.resolve({
      data: [{ id: 1, event_type: 'approved', created_at: '2026-07-27T12:00:00Z', detail: null }],
    })
  ),
  getAgentTelemetry: vi.fn(() => Promise.resolve({ data: { latest: null, readiness: [] } })),
  getAgentTelemetryHistory: vi.fn(() => Promise.resolve({ data: { points: [] } })),
  getAgentsPresence: vi.fn(() =>
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
    })
  ),
  setAgentCapabilities: vi.fn(),
  revokeAgent: vi.fn(),
  triggerAgentUpdate: vi.fn(),
}));

// See agents-page.test.jsx for why useAgentLive needs vi.hoisted() here.
const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/agents/3']}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('AgentDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
  });

  it('renders capabilities and the event timeline', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    expect(screen.getByText('approved')).toBeInTheDocument();
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
});
