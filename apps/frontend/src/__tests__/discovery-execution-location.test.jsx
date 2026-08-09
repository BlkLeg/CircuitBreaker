import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/discovery.js', () => ({
  getJobs: vi.fn().mockResolvedValue({ data: [] }),
  getJobResults: vi.fn().mockResolvedValue({ data: [] }),
  getJobLogs: vi.fn().mockResolvedValue({ data: [] }),
  cancelJob: vi.fn(),
  enrichOpnsenseJob: vi.fn(),
  getPendingResults: vi.fn().mockResolvedValue({ data: [] }),
  mergeResult: vi.fn().mockResolvedValue({ data: { entity_type: 'hardware', entity_id: 31 } }),
  enhancedBulkMerge: vi.fn().mockResolvedValue({ data: {} }),
  getDiscoveryStatus: vi.fn().mockResolvedValue({ data: { pending_results: 0, active_jobs: [] } }),
}));

vi.mock('../api/monitor.js', () => ({
  createTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
}));

vi.mock('../api/client.jsx', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  clustersApi: { list: vi.fn().mockResolvedValue([]) },
  networksApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  deviceRolesApi: {
    list: vi.fn().mockResolvedValue([
      { slug: 'server', label: 'Server', rank: 1, is_builtin: true },
      { slug: 'lxc', label: 'Container', rank: 2, is_builtin: true },
    ]),
  },
  computeUnitsApi: { list: vi.fn().mockResolvedValue([]) },
}));

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: { id: 1 }, token: 'test-token-value-12345' }),
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));

vi.mock('../utils/logger.js', () => ({
  __esModule: true,
  default: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

import DiscoveryHistoryPage from '../pages/DiscoveryHistoryPage.jsx';
import ScanDetailPanel, {
  DISCOVERY_ERROR_REASON_LABELS,
  SOURCE_COLORS,
} from '../components/discovery/ScanDetailPanel.jsx';
import ReviewQueuePanel from '../components/discovery/ReviewQueuePanel.jsx';
import { useDiscoveryStream } from '../hooks/useDiscoveryStream.js';
import { getPendingResults, mergeResult } from '../api/discovery.js';

const AGENTS = [
  { id: 7, name: 'edge-agent-01' },
  { id: 9, name: 'branch-agent' },
];

/** jsdom normalises inline colours to rgb(); mirror that for hex comparisons. */
function hexToRgb(hex) {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgb(${r}, ${g}, ${b})`;
}

function serverJob(overrides = {}) {
  return {
    id: 501,
    status: 'completed',
    source_type: 'manual',
    scan_agent_id: null,
    started_at: '2026-08-08T10:00:00Z',
    target_cidr: '10.0.0.0/24',
    scan_types_json: '["nmap"]',
    hosts_found: 4,
    hosts_new: 1,
    hosts_conflict: 0,
    ...overrides,
  };
}

function agentJob(overrides = {}) {
  return {
    id: 601,
    status: 'completed',
    source_type: 'agent',
    scan_agent_id: 7,
    started_at: '2026-08-08T11:00:00Z',
    target_cidr: '192.168.5.0/24',
    scan_types_json: '["agent_connect"]',
    hosts_found: 3,
    hosts_new: 3,
    hosts_conflict: 0,
    ...overrides,
  };
}

/**
 * A *component* contract: given a fleet, the table names the agent.
 *
 * It deliberately supplies `agents`, which is why it cannot see whether
 * anything in the product ever does — and for a while nothing did, so every
 * real row read `agent 7` while this file stayed green. The production path
 * (`DiscoveryPage` loading the fleet and passing it down) is asserted in
 * `discovery-page-fleet.test.jsx`; neither test stands alone.
 */
function renderHistory(jobsData, extraProps = {}) {
  return render(
    <MemoryRouter initialEntries={['/discovery']}>
      <DiscoveryHistoryPage embedded jobsData={jobsData} agents={AGENTS} {...extraProps} />
    </MemoryRouter>
  );
}

describe('DiscoveryHistoryPage — execution location', () => {
  it('names the Circuit Breaker server for a server-executed job', async () => {
    renderHistory([serverJob()]);

    await waitFor(() => expect(screen.getByText('10.0.0.0/24')).toBeInTheDocument());
    expect(screen.getByText('Circuit Breaker server')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('links the agent name to its detail page for an agent-executed job', async () => {
    renderHistory([agentJob()]);

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: 'edge-agent-01' });
    expect(link).toHaveAttribute('href', '/agents/7');
  });

  it('falls back to the agent id when the fleet list does not name it', async () => {
    renderHistory([agentJob({ scan_agent_id: 42 })]);

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'agent 42' })).toHaveAttribute('href', '/agents/42');
  });
});

describe('DiscoveryHistoryPage — the D-4 failure vocabulary', () => {
  it('renders a human label for each D-4 error_reason the server can send', async () => {
    const reasons = [
      'agent_unavailable',
      'agent_disconnected',
      'agent_execution_error',
      'agent_rejected',
      'dispatch_failed',
      'scope_changed',
      'capability_disabled',
      'profile_disabled',
    ];
    renderHistory(
      reasons.map((reason, index) =>
        agentJob({
          id: 700 + index,
          status: 'failed',
          error_reason: reason,
          target_cidr: `10.7.${index}.0/24`,
        })
      )
    );

    await waitFor(() => expect(screen.getByText('10.7.0.0/24')).toBeInTheDocument());
    // Scoped to the table: the same labels also name the filter's options.
    const rows = within(screen.getByRole('table'));
    for (const reason of reasons) {
      const label = DISCOVERY_ERROR_REASON_LABELS.get(reason);
      expect(label, `no label for ${reason}`).toBeTruthy();
      expect(label).not.toBe(reason);
      expect(rows.getByText(label)).toBeInTheDocument();
    }
  });

  it('says a failed agent scan kept its findings instead of showing a bare "failed"', async () => {
    renderHistory([
      agentJob({
        status: 'failed',
        error_reason: 'agent_execution_error',
        error_text: 'agent_execution_error: deadline_exceeded; partial_results_retained=3',
        hosts_found: 3,
      }),
    ]);

    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
    const rows = within(screen.getByRole('table'));
    expect(rows.getByText('Agent execution error')).toBeInTheDocument();
    expect(rows.getByText(/partial results/i).textContent).toMatch(/3 findings kept/i);
  });

  it('shows no partial note for a failure that retained nothing', async () => {
    renderHistory([
      agentJob({
        status: 'failed',
        error_reason: 'agent_disconnected',
        error_text: 'agent_disconnected',
        hosts_found: 0,
      }),
    ]);

    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
    const rows = within(screen.getByRole('table'));
    expect(rows.getByText('Agent disconnected')).toBeInTheDocument();
    expect(rows.queryByText(/partial results/i)).not.toBeInTheDocument();
  });

  it('filters the history by a D-4 error reason from the status filter', async () => {
    renderHistory([
      agentJob({ id: 801, status: 'failed', error_reason: 'agent_unavailable' }),
      agentJob({
        id: 802,
        status: 'failed',
        error_reason: 'dispatch_failed',
        target_cidr: '192.168.6.0/24',
      }),
    ]);

    await waitFor(() => expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument());
    const statusFilter = screen.getAllByRole('combobox')[1];
    expect(within(statusFilter).getByRole('option', { name: 'Agent unavailable' })).toBeTruthy();

    fireEvent.change(statusFilter, { target: { value: 'agent_unavailable' } });

    expect(screen.getByText('192.168.5.0/24')).toBeInTheDocument();
    expect(screen.queryByText('192.168.6.0/24')).not.toBeInTheDocument();
  });
});

describe('ScanDetailPanel — the agent execution location', () => {
  it('gives an agent-sourced job its own source colour', () => {
    expect(SOURCE_COLORS.agent).toBeTruthy();
    expect(SOURCE_COLORS.agent).not.toBe('#6b7280');

    render(
      <MemoryRouter>
        <ScanDetailPanel job={agentJob()} agentMap={new Map([[7, 'edge-agent-01']])} />
      </MemoryRouter>
    );

    const badge = screen.getByText('agent');
    expect(badge.style.color).toBe(hexToRgb(SOURCE_COLORS.agent));
  });

  it('links the agent name and explains a partial failure', () => {
    render(
      <MemoryRouter>
        <ScanDetailPanel
          job={agentJob({
            status: 'failed',
            error_reason: 'agent_execution_error',
            error_text: 'agent_execution_error: deadline_exceeded; partial_results_retained=2',
          })}
          agentMap={new Map([[7, 'edge-agent-01']])}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole('link', { name: 'edge-agent-01' })).toHaveAttribute(
      'href',
      '/agents/7'
    );
    expect(screen.getByText('Agent execution error')).toBeInTheDocument();
    expect(screen.getByText(/partial results/i).textContent).toMatch(/2 findings kept/i);
  });

  it('names the server for a server-executed job', () => {
    render(
      <MemoryRouter>
        <ScanDetailPanel job={serverJob()} />
      </MemoryRouter>
    );

    expect(screen.getByText('Circuit Breaker server')).toBeInTheDocument();
  });
});

describe('review queue — agent findings take the existing path', () => {
  it('renders and accepts an agent-sourced finding with no agent-specific UI', async () => {
    getPendingResults.mockResolvedValueOnce({
      data: [
        {
          id: 9001,
          scan_job_id: 601,
          ip_address: '192.168.5.20',
          mac_address: 'aa:bb:cc:00:11:22',
          hostname: 'nas',
          state: 'new',
          merge_status: 'pending',
          os_family: 'Linux',
          os_vendor: 'Synology',
        },
      ],
    });

    render(
      <MemoryRouter>
        <ReviewQueuePanel />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('192.168.5.20')).toBeInTheDocument());

    // Same row shape as a server finding: the ordinary state pill, and no
    // agent badge, agent column, or agent-only action anywhere in the queue.
    expect(screen.getByText('New')).toBeInTheDocument();
    expect(screen.queryByText(/agent/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /agent/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByTitle('Accept')[0]);

    await waitFor(() =>
      expect(mergeResult).toHaveBeenCalledWith(9001, expect.objectContaining({ action: 'accept' }))
    );
  });
});

// ── The review badge ─────────────────────────────────────────────────────────

const socketInstances = [];

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.close = vi.fn(() => {
      this.readyState = MockWebSocket.CLOSED;
      this.onclose?.({ code: 1000 });
    });
    this.send = vi.fn();
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this.listeners = new Map();
    socketInstances.push(this);
  }

  addEventListener(event, callback) {
    const callbacks = this.listeners.get(event) || [];
    callbacks.push(callback);
    this.listeners.set(event, callbacks);
  }

  emitOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
    const callbacks = this.listeners.get('open') || [];
    callbacks.forEach((callback) => callback());
    this.listeners.set('open', []);
  }

  emitMessage(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

describe('useDiscoveryStream — the pending badge', () => {
  beforeEach(() => {
    socketInstances.length = 0;
    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("replaces its optimistic count with the server's pending_count", async () => {
    const { result } = renderHook(() => useDiscoveryStream());
    const socket = socketInstances[socketInstances.length - 1];

    // Let the mount-time /discovery/status sync settle, so nothing but the
    // frames below can move the count afterwards.
    await act(async () => {});
    expect(result.current.pendingCount).toBe(0);

    act(() => {
      socket.emitOpen();
      socket.emitMessage({ status: 'connected' });
    });

    act(() => {
      socket.emitMessage({ type: 'result_added', result: { id: 1, ip_address: '192.168.5.20' } });
      socket.emitMessage({ type: 'result_added', result: { id: 2, ip_address: '192.168.5.21' } });
    });
    expect(result.current.pendingCount).toBe(2);

    // An agent job streams findings in while somebody else reviews them, so the
    // optimistic count is already wrong by the time this frame lands.
    act(() => {
      socket.emitMessage({
        type: 'result_processed',
        result_id: 1,
        action: 'accept',
        pending_count: 7,
      });
    });

    expect(result.current.pendingCount).toBe(7);
  });
});
