import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/monitor', () => ({
  getMonitorsOverview: vi.fn(),
  getMonitorEvents: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorHistory: vi.fn().mockResolvedValue({ data: [] }),
  createMonitor: vi.fn().mockResolvedValue({ data: {} }),
  updateMonitor: vi.fn().mockResolvedValue({ data: {} }),
  deleteMonitor: vi.fn().mockResolvedValue({ data: {} }),
  pauseMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runCheck: vi.fn().mockResolvedValue({ data: {} }),
}));

let mockStatuses = new Map();
vi.mock('../hooks/useMonitorStream', () => ({
  useMonitorStream: () => ({ statuses: mockStatuses, connected: true }),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));
vi.mock('../components/monitors/MonitorForm', () => ({
  default: ({ onCancel }) => (
    <div data-testid="form">
      <button onClick={onCancel}>close form</button>
    </div>
  ),
}));
vi.mock('../components/monitors/LatencyChart', () => ({ default: () => <div>chart</div> }));
// Same treatment discovery-page.test.jsx gives discovery.css — a real CSS import
// blows up the jsdom environment during collection.
vi.mock('../styles/monitors.css', () => ({}));

import {
  getMonitorEvents,
  getMonitorHistory,
  getMonitorsOverview,
  pauseMonitor,
  runCheck,
} from '../api/monitor';
import MonitorsPage from '../pages/MonitorsPage.jsx';

const row = (over) => ({
  id: 1,
  name: 'pve',
  check_type: 'icmp',
  host: '192.168.0.4',
  config: {},
  status: 'up',
  enabled: true,
  interval_secs: 60,
  retries: 0,
  max_retries: 0,
  uptime_pct_24h: 100,
  latency_ms: 13,
  last_polled_at: new Date().toISOString(),
  last_status_change_at: new Date().toISOString(),
  target_type: 'hardware',
  target_id: 30,
  latency_series: [10, 12, 13],
  recent_checks: [],
  ...over,
});

const fleet = [
  row({ id: 1, name: 'pve' }),
  row({
    id: 2,
    name: 'grafana',
    check_type: 'http',
    config: { url: 'https://grafana.lan' },
    status: 'down',
    latency_ms: null,
    uptime_pct_24h: 41,
    target_type: null,
    latency_series: [],
    recent_checks: [
      { id: 5, status_to: 'down', msg: 'timeout', created_at: '2026-07-26T12:41:09Z' },
    ],
  }),
  row({ id: 3, name: 'old-nas', enabled: false, status: 'up' }),
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/monitors']}>
      <MonitorsPage />
    </MemoryRouter>
  );
}

describe('MonitorsPage dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatuses = new Map();
    getMonitorsOverview.mockResolvedValue({ data: fleet });
    getMonitorEvents.mockResolvedValue({ data: [] });
    getMonitorHistory.mockResolvedValue({ data: [] });
  });

  it('costs exactly one request for the whole wall', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    expect(getMonitorsOverview).toHaveBeenCalledTimes(1);
    expect(getMonitorEvents).not.toHaveBeenCalled();
  });

  it('summarises the fleet and groups it worst-first', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('grafana')).toBeTruthy());

    expect(screen.getByRole('button', { name: 'Total 3' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Up 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Down 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Paused 1' })).toBeTruthy();

    const headings = [...container.querySelectorAll('.mon-group-title')].map((h) =>
      h.textContent.trim()
    );
    expect(headings[0]).toContain('Down');
    expect(headings[headings.length - 1]).toContain('Paused');
  });

  it('filters by status from a tile', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Down 1' }));
    await waitFor(() => expect(screen.queryByText('pve')).toBeNull());
    expect(screen.getByText('grafana')).toBeTruthy();
  });

  it('filters by check type and by search text', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'HTTP 1' }));
    await waitFor(() => expect(screen.queryByText('pve')).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: 'HTTP 1' }));
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Search monitors'), { target: { value: 'graf' } });
    await waitFor(() => expect(screen.queryByText('pve')).toBeNull());
    expect(screen.getByText('grafana')).toBeTruthy();
  });

  it('offers a way back when filters hide everything', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Search monitors'), { target: { value: 'zzz' } });
    await waitFor(() => expect(screen.getByText('No monitors match.')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
  });

  it('fetches a card detail once when expanded', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());

    const face = screen.getByText('pve').closest('button');
    fireEvent.click(face);
    await waitFor(() => expect(getMonitorHistory).toHaveBeenCalledWith(1, { hours: 24 }));
    expect(getMonitorEvents).toHaveBeenCalledWith(1, 40);

    fireEvent.click(face);
    fireEvent.click(face);
    await waitFor(() => expect(screen.getByText('Check now')).toBeTruthy());
    expect(getMonitorHistory).toHaveBeenCalledTimes(1);
  });

  it('runs actions from the expanded card', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    fireEvent.click(screen.getByText('pve').closest('button'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Check now' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
    await waitFor(() => expect(runCheck).toHaveBeenCalledWith(1));

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(pauseMonitor).toHaveBeenCalledWith(1));
  });

  it('folds live status pushes into the wall', async () => {
    const { rerender } = renderPage();
    await waitFor(() => expect(screen.getByText('13 ms')).toBeTruthy());

    mockStatuses = new Map([[1, { status: 'down', msg: 'timeout', ts: new Date().toISOString() }]]);
    rerender(
      <MemoryRouter initialEntries={['/monitors']}>
        <MonitorsPage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'Down 2' })).toBeTruthy());
  });

  it('invites the first monitor when there are none', async () => {
    getMonitorsOverview.mockResolvedValue({ data: [] });
    renderPage();
    await waitFor(() => expect(screen.getByText(/No monitors yet/)).toBeTruthy());
  });
});
