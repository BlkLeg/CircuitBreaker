import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/monitors/MonitorCardDetail.jsx', () => ({
  default: ({ monitor }) => <div data-testid="detail">detail for {monitor.name}</div>,
}));

import MonitorCard, { groupStatusOf, headlineOf } from '../components/monitors/MonitorCard.jsx';

const up = {
  id: 1,
  name: 'pve',
  check_type: 'icmp',
  host: '192.168.0.4',
  config: {},
  status: 'up',
  enabled: true,
  latency_ms: 13.6,
  uptime_pct_24h: 100,
  retries: 0,
  max_retries: 0,
  target_type: 'hardware',
  latency_series: [4, 8, 12],
  recent_checks: [],
};

const down = {
  ...up,
  id: 2,
  name: 'grafana',
  check_type: 'http',
  config: { url: 'https://grafana.lan/login' },
  status: 'down',
  latency_ms: null,
  uptime_pct_24h: 41,
  target_type: null,
  latency_series: [],
  recent_checks: [{ id: 9, status_to: 'down', msg: 'timeout', created_at: '2026-07-26T12:41:09Z' }],
};

function renderCard(monitor, overrides = {}) {
  const props = {
    monitor,
    expanded: false,
    onToggle: vi.fn(),
    detail: undefined,
    busy: false,
    onCheckNow: vi.fn(),
    onPause: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  const utils = render(
    <MemoryRouter>
      <MonitorCard {...props} />
    </MemoryRouter>
  );
  return { ...utils, props };
}

describe('MonitorCard', () => {
  it('shows a sparkline and latency for a healthy monitor', () => {
    const { container } = renderCard(up);
    expect(screen.getByText('pve')).toBeTruthy();
    expect(screen.getByText('ICMP')).toBeTruthy();
    expect(screen.getByText('192.168.0.4 · hardware')).toBeTruthy();
    expect(screen.getByText('14 ms')).toBeTruthy();
    expect(container.querySelector('.mon-spark')).toBeTruthy();
    expect(container.querySelector('.mon-card').dataset.status).toBe('up');
  });

  it('shows the check history and the target URL for a failing monitor', () => {
    const { container } = renderCard(down);
    expect(screen.getByText('Down')).toBeTruthy();
    expect(screen.getByText('https://grafana.lan/login')).toBeTruthy();
    expect(container.querySelector('.mon-spark')).toBeNull();
    expect(container.querySelector('[aria-label="check history"]')).toBeTruthy();
    expect(container.querySelector('.mon-card').dataset.status).toBe('down');
  });

  it('reads as paused when disabled, whatever its last status', () => {
    const { container } = renderCard({ ...up, enabled: false });
    expect(screen.getByText('Paused')).toBeTruthy();
    expect(container.querySelector('.mon-card').dataset.status).toBe('paused');
  });

  it('toggles on click and reports its expanded state', () => {
    const { props, rerender } = renderCard(up);
    const face = screen.getByRole('button', { expanded: false });
    fireEvent.click(face);
    expect(props.onToggle).toHaveBeenCalledWith(1);

    rerender(
      <MemoryRouter>
        <MonitorCard {...props} expanded detail={{ history: [], events: [], loading: false }} />
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { expanded: true })).toBeTruthy();
    expect(screen.getByTestId('detail')).toBeTruthy();
  });

  it('derives its group and headline', () => {
    expect(groupStatusOf(up)).toBe('up');
    expect(groupStatusOf({ ...up, enabled: false })).toBe('paused');
    expect(headlineOf(up)).toBe('14 ms');
    expect(headlineOf({ ...up, latency_ms: null })).toBe('Up');
    expect(headlineOf(down)).toBe('Down');
    expect(headlineOf({ ...up, status: 'pending', retries: 1, max_retries: 2 })).toBe('Retry 1/2');
    expect(headlineOf({ ...up, status: 'pending', max_retries: 0 })).toBe('Pending');
    expect(headlineOf({ ...up, enabled: false })).toBe('Paused');
  });
});
