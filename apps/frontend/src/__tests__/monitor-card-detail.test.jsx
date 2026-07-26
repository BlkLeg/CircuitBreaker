import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/monitors/LatencyChart.jsx', () => ({
  default: ({ points }) => <div data-testid="chart">{points.length} points</div>,
}));

import MonitorCardDetail from '../components/monitors/MonitorCardDetail.jsx';

const monitor = {
  id: 4,
  name: 'grafana',
  check_type: 'http',
  host: 'grafana.lan',
  config: { url: 'https://grafana.lan/login' },
  status: 'down',
  enabled: true,
  interval_secs: 60,
  retries: 2,
  max_retries: 2,
  uptime_pct_24h: 41,
  latency_ms: null,
  last_status_change_at: new Date(Date.now() - 372_000).toISOString(),
  target_type: 'service',
  target_id: 9,
};

const events = [
  {
    id: 2,
    status_to: 'down',
    msg: 'connect timeout after 10s',
    created_at: '2026-07-26T12:41:09Z',
  },
  { id: 1, status_to: 'pending', msg: 'retry 1/2', created_at: '2026-07-26T12:39:07Z' },
];

function renderDetail(overrides = {}) {
  const props = {
    monitor,
    history: [
      { ts: '2026-07-26T12:00:00Z', value: 30 },
      { ts: '2026-07-26T12:01:00Z', value: 34 },
    ],
    events,
    loading: false,
    busy: false,
    onCheckNow: vi.fn(),
    onPause: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  render(
    <MemoryRouter>
      <MonitorCardDetail {...props} />
    </MemoryRouter>
  );
  return props;
}

describe('MonitorCardDetail', () => {
  it('shows the chart, the four stats and the recent events', () => {
    renderDetail();
    expect(screen.getByTestId('chart').textContent).toBe('2 points');
    expect(screen.getByText('41%')).toBeTruthy();
    expect(screen.getByText('2 / 2')).toBeTruthy();
    expect(screen.getByText('6m 12s')).toBeTruthy();
    expect(screen.getByText(/connect timeout after 10s/)).toBeTruthy();
  });

  it('runs each action', () => {
    const props = renderDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
    expect(props.onCheckNow).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(props.onPause).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(props.onEdit).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(props.onDelete).toHaveBeenCalled();
  });

  it('offers Resume for a paused monitor', () => {
    renderDetail({ monitor: { ...monitor, enabled: false } });
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
  });

  it('disables the actions while a request is in flight', () => {
    renderDetail({ busy: true });
    expect(screen.getByRole('button', { name: 'Check now' }).disabled).toBe(true);
  });

  it('says so while the detail is still loading', () => {
    renderDetail({ loading: true, history: [], events: [] });
    expect(screen.getByText('Loading check history…')).toBeTruthy();
  });
});
