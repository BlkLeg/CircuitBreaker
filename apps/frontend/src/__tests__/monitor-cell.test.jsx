import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MonitorCell, { MonitorStatusCell } from '../components/monitors/MonitorCell.jsx';

const noop = () => {};

describe('MonitorCell', () => {
  it('offers Monitor when the entity has no monitor yet', async () => {
    const onEnable = vi.fn().mockResolvedValue();
    render(
      <MonitorCell
        state={null}
        onEnable={onEnable}
        onPause={noop}
        onResume={noop}
        onCheckNow={noop}
      />
    );

    const btn = screen.getByRole('button', { name: 'Monitor' });
    fireEvent.click(btn);
    await waitFor(() => expect(onEnable).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
  });

  it('offers Pause and Check while enabled', async () => {
    const onPause = vi.fn().mockResolvedValue();
    const onCheckNow = vi.fn().mockResolvedValue();
    render(
      <MonitorCell
        state={{ monitor_id: 3, monitor_ids: [3], enabled: true, status: 'up' }}
        onEnable={noop}
        onPause={onPause}
        onResume={noop}
        onCheckNow={onCheckNow}
      />
    );

    expect(screen.queryByRole('button', { name: 'Monitor' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(onPause).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    await waitFor(() => expect(onCheckNow).toHaveBeenCalledTimes(1));
  });

  it('offers Resume while paused', async () => {
    const onResume = vi.fn().mockResolvedValue();
    render(
      <MonitorCell
        state={{ monitor_id: 3, monitor_ids: [3], enabled: false, status: 'up' }}
        onEnable={noop}
        onPause={noop}
        onResume={onResume}
        onCheckNow={noop}
      />
    );

    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    await waitFor(() => expect(onResume).toHaveBeenCalledTimes(1));
  });

  it('disables its buttons while an action is in flight', async () => {
    let release;
    const onEnable = vi.fn(() => new Promise((r) => (release = r)));
    render(
      <MonitorCell
        state={null}
        onEnable={onEnable}
        onPause={noop}
        onResume={noop}
        onCheckNow={noop}
      />
    );

    const btn = screen.getByRole('button', { name: 'Monitor' });
    fireEvent.click(btn);
    await waitFor(() => expect(btn).toBeDisabled());
    release();
    await waitFor(() => expect(btn).not.toBeDisabled());
  });
});

describe('MonitorStatusCell', () => {
  it('renders a dash when unmonitored', () => {
    const { container } = render(<MonitorStatusCell state={null} />);
    expect(container.textContent).toBe('—');
  });

  it('renders the status with uptime and latency in the tooltip', () => {
    render(
      <MonitorStatusCell
        state={{ status: 'up', enabled: true, uptime_pct_24h: 99.5, latency_ms: 12.4 }}
      />
    );
    const pill = screen.getByText('Up');
    expect(pill.getAttribute('title')).toBe('99.5% uptime (24h) · 12 ms');
  });

  it('shows Paused instead of the last status when disabled', () => {
    render(<MonitorStatusCell state={{ status: 'up', enabled: false }} />);
    expect(screen.getByText('Paused')).toBeTruthy();
  });
});
