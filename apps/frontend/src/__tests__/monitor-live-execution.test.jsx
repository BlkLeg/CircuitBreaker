import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// D-13: an execution-condition refresh publishes {monitor_id,
// probe_execution_status, probe_execution_reason, ts} with **no** status key,
// because the vantage becoming unavailable is not a target transition. These
// tests pin that the wall's fold never invents one.
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
vi.mock('../components/monitors/MonitorForm', () => ({ default: () => <div /> }));
vi.mock('../components/monitors/LatencyChart', () => ({ default: () => <div>chart</div> }));
vi.mock('../styles/monitors.css', () => ({}));

import { getMonitorEvents, getMonitorHistory, getMonitorsOverview } from '../api/monitor';
import MonitorsPage from '../pages/MonitorsPage.jsx';

const assigned = {
  id: 1,
  name: 'branch nas',
  check_type: 'icmp',
  host: '10.0.0.9',
  config: {},
  status: 'up',
  enabled: true,
  interval_secs: 60,
  retries: 0,
  max_retries: 0,
  uptime_pct_24h: 100,
  latency_ms: 13,
  last_polled_at: '2026-08-07T09:00:00Z',
  last_status_change_at: '2026-08-07T08:00:00Z',
  target_type: 'hardware',
  target_id: 5,
  latency_series: [10, 12, 13],
  recent_checks: [],
  probe_agent_id: 7,
  probe_mode: 'agent',
  probe_agent: { id: 7, name: 'branch-office' },
  probe_execution_status: 'ready',
  probe_execution_reason: null,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/monitors']}>
      <MonitorsPage />
    </MemoryRouter>
  );
}

const rerenderPage = (rerender) =>
  rerender(
    <MemoryRouter initialEntries={['/monitors']}>
      <MonitorsPage />
    </MemoryRouter>
  );

beforeEach(() => {
  vi.clearAllMocks();
  mockStatuses = new Map();
  getMonitorsOverview.mockResolvedValue({ data: [assigned] });
  getMonitorEvents.mockResolvedValue({ data: [] });
  getMonitorHistory.mockResolvedValue({ data: [] });
});

describe('MonitorsPage live execution-condition fold', () => {
  it('a push carrying only probe_execution_status leaves the status pill untouched', async () => {
    const { container, rerender } = renderPage();
    await waitFor(() => expect(screen.getByText('13 ms')).toBeTruthy());
    expect(container.querySelector('.mon-card').dataset.status).toBe('up');

    mockStatuses = new Map([
      [
        1,
        {
          type: 'monitor_status',
          monitor_id: 1,
          probe_execution_status: 'unavailable',
          probe_execution_reason: 'agent_offline',
          ts: '2026-08-07T09:01:00Z',
        },
      ],
    ]);
    rerenderPage(rerender);

    await waitFor(() =>
      expect(container.querySelector('.mon-exec').textContent).toBe('probe unavailable')
    );
    // Target state, headline, summary counts and the check history are all
    // exactly as they were — only the secondary condition moved.
    expect(container.querySelector('.mon-card').dataset.status).toBe('up');
    expect(screen.getByText('13 ms')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Up 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Down 0' })).toBeTruthy();
    expect(container.querySelectorAll('[aria-label="check history"] > *')).toHaveLength(0);
  });

  it('a push carrying status still updates the pill', async () => {
    const { container, rerender } = renderPage();
    await waitFor(() => expect(screen.getByText('13 ms')).toBeTruthy());

    mockStatuses = new Map([
      [
        1,
        {
          type: 'monitor_status',
          monitor_id: 1,
          status: 'down',
          msg: '100% packet loss (5 probes)',
          ts: '2026-08-07T09:02:00Z',
        },
      ],
    ]);
    rerenderPage(rerender);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Down 1' })).toBeTruthy());
    expect(container.querySelector('.mon-card').dataset.status).toBe('down');
    expect(container.querySelector('.mon-headline').textContent).toBe('Down');
    // The last execution condition the server told us about survives a target
    // transition; nothing in the push claims to know about the vantage.
    expect(container.querySelector('.mon-exec')).toBeNull();
  });
});
