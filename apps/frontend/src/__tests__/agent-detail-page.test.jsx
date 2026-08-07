import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  // Task 14: HOST_DEFAULTS is gone from the page; the host-telemetry config
  // key list and every fallback value come from the server registry. This
  // fixture deliberately carries a key the frontend has never heard of
  // (`include_gpu`) so the test proves the page renders whatever the server
  // declares rather than a hardcoded copy.
  getCapabilityDefaults: vi.fn(() =>
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
    })
  ),
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
});
