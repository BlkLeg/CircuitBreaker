import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: '7' }),
}));

vi.mock('../api/monitor', () => ({
  getMonitor: vi.fn(),
  getMonitorEvents: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorHistory: vi.fn().mockResolvedValue({ data: [] }),
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

import { getMonitor, getMonitorUptime } from '../api/monitor';
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

beforeEach(() => {
  vi.clearAllMocks();
  getMonitor.mockResolvedValue({ data: monitor });
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
