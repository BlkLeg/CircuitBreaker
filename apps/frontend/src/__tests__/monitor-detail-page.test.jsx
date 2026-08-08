import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: '7' }),
  Link: ({ to, children }) => <a href={to}>{children}</a>,
}));

vi.mock('../api/monitor', () => ({
  getMonitor: vi.fn(),
  getMonitorEvents: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorHistory: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorProbeRuns: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorUptime: vi.fn(),
  pauseMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runCheck: vi.fn().mockResolvedValue({ data: {} }),
}));

vi.mock('../hooks/useMonitorStream', () => ({
  useMonitorStream: () => ({ statuses: new Map() }),
}));

const mockToast = { success: vi.fn(), error: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));
vi.mock('../components/monitors/LatencyChart', () => ({ default: () => <div>chart</div> }));
vi.mock('../components/monitors/CheckHistoryBar', () => ({ default: () => <div>history</div> }));
vi.mock('../components/monitors/StatusPill', () => ({ default: () => <div>status</div> }));

import {
  getMonitor,
  getMonitorEvents,
  getMonitorProbeRuns,
  getMonitorUptime,
} from '../api/monitor';
import MonitorDetailPage from '../pages/MonitorDetailPage.jsx';

const monitor = {
  id: 7,
  name: 'edge web',
  check_type: 'http',
  host: '192.0.2.7',
  config: { url: 'https://192.0.2.7/health' },
  status: 'up',
  enabled: true,
  interval_secs: 60,
  last_polled_at: '2026-07-26T18:00:00Z',
};

const noUptime = {
  data: {
    pct_24h: null,
    pct_7d: null,
    pct_30d: null,
    pct_365d: null,
    pct_total: null,
    last_polled_at: null,
  },
};

// `vi.clearAllMocks()` clears call records but leaves implementations installed,
// so every implementation a test may override is re-applied here.
beforeEach(() => {
  vi.clearAllMocks();
  getMonitor.mockResolvedValue({ data: monitor });
  getMonitorEvents.mockResolvedValue({ data: [] });
  getMonitorProbeRuns.mockResolvedValue({ data: [] });
});

describe('MonitorDetailPage uptime stats', () => {
  it('shows all six availability stats once loaded', async () => {
    getMonitorUptime.mockResolvedValue({
      data: {
        pct_24h: 99.8,
        pct_7d: 99.5,
        pct_30d: 98.9,
        pct_365d: 99.1,
        pct_total: 99.3,
        last_polled_at: '2026-07-26T18:05:00Z',
      },
    });
    render(<MonitorDetailPage />);
    await waitFor(() => expect(screen.getByText('Total Uptime')).toBeTruthy());
    expect(screen.getByText('Last Polled')).toBeTruthy();
    expect(screen.getByText('24 Hour')).toBeTruthy();
    expect(screen.getByText('7-Day')).toBeTruthy();
    expect(screen.getByText('30-Day')).toBeTruthy();
    expect(screen.getByText('365-Day')).toBeTruthy();
    expect(screen.getByText('99.8%')).toBeTruthy();
    expect(screen.getByText('99.5%')).toBeTruthy();
    expect(screen.getByText('98.9%')).toBeTruthy();
    expect(screen.getByText('99.1%')).toBeTruthy();
    expect(screen.getByText('99.3%')).toBeTruthy();
  });

  it('renders — for stats with no data yet', async () => {
    getMonitorUptime.mockResolvedValue({
      data: {
        pct_24h: null,
        pct_7d: null,
        pct_30d: null,
        pct_365d: null,
        pct_total: null,
        last_polled_at: null,
      },
    });
    render(<MonitorDetailPage />);
    await waitFor(() => expect(screen.getByText('Total Uptime')).toBeTruthy());
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(5);
  });
});

describe('MonitorDetailPage probe vantage', () => {
  const agentMonitor = {
    ...monitor,
    probe_agent_id: 7,
    probe_mode: 'agent',
    probe_agent: { id: 7, name: 'branch-office' },
    probe_execution_status: 'unavailable',
    probe_execution_reason: 'agent_offline',
  };

  const targetEvent = {
    id: 1,
    status_from: 'up',
    status_to: 'down',
    msg: 'connect timeout after 10s',
    created_at: '2026-08-07T09:00:00Z',
    duration_secs: 42,
  };

  const probeRun = {
    run_id: 'run-abc',
    agent_id: 7,
    status: 'expired',
    outcome: 'execution_error',
    msg: 'agent went offline before the deadline',
    error_code: 'result_timeout',
    scheduled_at: '2026-08-07T09:05:00Z',
    dispatched_at: '2026-08-07T09:05:01Z',
    deadline_at: '2026-08-07T09:05:31Z',
    started_at: null,
    completed_at: null,
    attempt_count: 1,
    created_at: '2026-08-07T09:05:00Z',
  };

  it('shows the run-from vantage and the execution condition beside target state', async () => {
    getMonitor.mockResolvedValue({ data: agentMonitor });
    getMonitorUptime.mockResolvedValue(noUptime);
    render(<MonitorDetailPage />);

    await waitFor(() => expect(screen.getByText('Run from')).toBeTruthy());
    expect(screen.getByRole('link', { name: 'branch-office' }).getAttribute('href')).toBe(
      '/agents/7'
    );
    expect(screen.getByText('Execution status')).toBeTruthy();
    expect(screen.getByText('unavailable (agent_offline)')).toBeTruthy();
  });

  it('renders probe runs in a table separate from target events', async () => {
    getMonitor.mockResolvedValue({ data: agentMonitor });
    getMonitorUptime.mockResolvedValue(noUptime);
    getMonitorEvents.mockResolvedValue({ data: [targetEvent] });
    getMonitorProbeRuns.mockResolvedValue({ data: [probeRun] });
    render(<MonitorDetailPage />);

    await waitFor(() => expect(screen.getByRole('region', { name: 'Probe runs' })).toBeTruthy());
    expect(getMonitorProbeRuns).toHaveBeenCalledWith(7, 20);

    const runs = within(screen.getByRole('region', { name: 'Probe runs' }));
    const events = within(screen.getByRole('region', { name: 'Events' }));
    expect(runs.getByText('result_timeout')).toBeTruthy();
    expect(runs.getByText('execution_error')).toBeTruthy();
    expect(events.getByText('connect timeout after 10s')).toBeTruthy();
    // Two tables, not one merged log.
    expect(runs.getByRole('table')).not.toBe(events.getByRole('table'));
  });

  it('execution errors do not appear in the target event list', async () => {
    getMonitor.mockResolvedValue({ data: agentMonitor });
    getMonitorUptime.mockResolvedValue(noUptime);
    getMonitorEvents.mockResolvedValue({ data: [targetEvent] });
    getMonitorProbeRuns.mockResolvedValue({ data: [probeRun] });
    render(<MonitorDetailPage />);

    await waitFor(() => expect(screen.getByRole('region', { name: 'Probe runs' })).toBeTruthy());
    const events = within(screen.getByRole('region', { name: 'Events' }));
    expect(events.queryByText('agent went offline before the deadline')).toBeNull();
    expect(events.queryByText('result_timeout')).toBeNull();
    expect(events.getAllByRole('row')).toHaveLength(2); // header + the one target transition
  });

  it('asks for no probe runs and reports the server as the vantage when unassigned', async () => {
    getMonitorUptime.mockResolvedValue(noUptime);
    render(<MonitorDetailPage />);

    await waitFor(() => expect(screen.getByText('Circuit Breaker server')).toBeTruthy());
    expect(getMonitorProbeRuns).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'Probe runs' })).toBeNull();
  });
});
