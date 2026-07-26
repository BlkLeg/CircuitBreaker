import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../api/monitor', () => ({
  getTargetSummary: vi.fn(),
  createTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  pauseTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeTargetMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runTargetCheck: vi.fn().mockResolvedValue({ data: {} }),
}));

// The hook shares the app's monitors socket; drive it directly from the test.
let mockStatuses = new Map();
vi.mock('../hooks/useMonitorStream', () => ({
  useMonitorStream: () => ({ statuses: mockStatuses, connected: true }),
}));

import {
  createTargetMonitor,
  getTargetSummary,
  pauseTargetMonitor,
  runTargetCheck,
} from '../api/monitor';
import { useTargetMonitors } from '../hooks/useTargetMonitors';

function Probe({ ids }) {
  const monitors = useTargetMonitors('compute_unit', ids);
  const row = monitors.byId[7];
  return (
    <div>
      <span data-testid="loading">{String(monitors.loading)}</span>
      <span data-testid="status">{row ? row.status : 'none'}</span>
      <span data-testid="uptime">{row ? String(row.uptime_pct_24h) : '-'}</span>
      <button onClick={() => monitors.enable(7)}>enable</button>
      <button onClick={() => monitors.pause(7)}>pause</button>
      <button onClick={() => monitors.checkNow(7)}>check</button>
    </div>
  );
}

const SUMMARY = [
  {
    target_type: 'compute_unit',
    target_id: 7,
    monitor_id: 31,
    monitor_ids: [31],
    enabled: true,
    status: 'up',
    latency_ms: 4.2,
    uptime_pct_24h: 99.9,
    last_polled_at: null,
  },
];

describe('useTargetMonitors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatuses = new Map();
    getTargetSummary.mockResolvedValue({ data: SUMMARY });
  });

  it('loads the rollup and keys it by target id', async () => {
    render(<Probe ids={[7]} />);
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('up'));
    expect(screen.getByTestId('uptime').textContent).toBe('99.9');
    expect(getTargetSummary).toHaveBeenCalledWith('compute_unit');
  });

  it('skips the request when the page has no rows', async () => {
    render(<Probe ids={[]} />);
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(getTargetSummary).not.toHaveBeenCalled();
  });

  it('folds a pushed status over the fetched rollup', async () => {
    mockStatuses = new Map([[31, { monitor_id: 31, status: 'down' }]]);
    render(<Probe ids={[7]} />);
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('down'));
    // The rest of the row is preserved.
    expect(screen.getByTestId('uptime').textContent).toBe('99.9');
  });

  it('refreshes after every action', async () => {
    render(<Probe ids={[7]} />);
    await waitFor(() => expect(getTargetSummary).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText('enable'));
    await waitFor(() =>
      expect(createTargetMonitor).toHaveBeenCalledWith('compute_unit', 7, undefined)
    );
    await waitFor(() => expect(getTargetSummary).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByText('pause'));
    await waitFor(() => expect(pauseTargetMonitor).toHaveBeenCalledWith('compute_unit', 7));

    fireEvent.click(screen.getByText('check'));
    await waitFor(() => expect(runTargetCheck).toHaveBeenCalledWith('compute_unit', 7));
  });

  it('surfaces a load failure without throwing', async () => {
    getTargetSummary.mockRejectedValue(new Error('boom'));
    render(<Probe ids={[7]} />);
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('status').textContent).toBe('none');
  });
});
