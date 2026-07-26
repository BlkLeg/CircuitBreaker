import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MonitorSummaryStrip from '../components/monitors/MonitorSummaryStrip.jsx';

const counts = { total: 18, up: 13, down: 2, pending: 1, paused: 2 };

describe('MonitorSummaryStrip', () => {
  it('shows a count per status', () => {
    render(<MonitorSummaryStrip counts={counts} active={null} onSelect={() => {}} />);
    expect(screen.getByRole('button', { name: 'Total 18' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Down 2' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Paused 2' })).toBeTruthy();
  });

  it('selects a status filter and clears it on a second click', () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <MonitorSummaryStrip counts={counts} active={null} onSelect={onSelect} />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Down 2' }));
    expect(onSelect).toHaveBeenCalledWith('down');

    rerender(<MonitorSummaryStrip counts={counts} active="down" onSelect={onSelect} />);
    expect(screen.getByRole('button', { name: 'Down 2' }).getAttribute('aria-pressed')).toBe(
      'true'
    );
    fireEvent.click(screen.getByRole('button', { name: 'Down 2' }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('clears the filter from the Total tile', () => {
    const onSelect = vi.fn();
    render(<MonitorSummaryStrip counts={counts} active="up" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button', { name: 'Total 18' }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
