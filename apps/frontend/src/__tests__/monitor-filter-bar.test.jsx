import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MonitorFilterBar from '../components/monitors/MonitorFilterBar.jsx';

const base = {
  q: '',
  onQ: () => {},
  type: null,
  onType: () => {},
  typeCounts: { http: 6, icmp: 9 },
  sort: 'worst',
  onSort: () => {},
};

describe('MonitorFilterBar', () => {
  it('renders a chip per present check type with its count', () => {
    render(<MonitorFilterBar {...base} />);
    expect(screen.getByRole('button', { name: 'HTTP 6' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'ICMP 9' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /DNS/ })).toBeNull();
  });

  it('toggles a type filter', () => {
    const onType = vi.fn();
    const { rerender } = render(<MonitorFilterBar {...base} onType={onType} />);
    fireEvent.click(screen.getByRole('button', { name: 'HTTP 6' }));
    expect(onType).toHaveBeenCalledWith('http');

    rerender(<MonitorFilterBar {...base} type="http" onType={onType} />);
    fireEvent.click(screen.getByRole('button', { name: 'HTTP 6' }));
    expect(onType).toHaveBeenLastCalledWith(null);
  });

  it('reports search text and sort changes', () => {
    const onQ = vi.fn();
    const onSort = vi.fn();
    render(<MonitorFilterBar {...base} onQ={onQ} onSort={onSort} />);
    fireEvent.change(screen.getByPlaceholderText('Search name or target…'), {
      target: { value: 'graf' },
    });
    expect(onQ).toHaveBeenCalledWith('graf');
    fireEvent.change(screen.getByLabelText('Sort monitors'), { target: { value: 'latency' } });
    expect(onSort).toHaveBeenCalledWith('latency');
  });
});
