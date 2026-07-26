import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import LatencySparkline from '../components/monitors/LatencySparkline.jsx';
import { formatAgo, formatSince } from '../components/monitors/monitorFormat.js';

describe('LatencySparkline', () => {
  it('draws one bar per sample, scaled to the tallest', () => {
    const { container } = render(<LatencySparkline series={[5, 10, 20]} height={20} />);
    const bars = container.querySelectorAll('.mon-spark span');
    expect(bars).toHaveLength(3);
    expect(bars[2].style.height).toBe('20px');
    expect(bars[0].style.height).toBe('5px');
  });

  it('renders nothing without samples', () => {
    const { container } = render(<LatencySparkline series={[]} />);
    expect(container.querySelector('.mon-spark')).toBeNull();
  });

  it('keeps a flat series visible', () => {
    const { container } = render(<LatencySparkline series={[0, 0]} height={20} />);
    const bars = container.querySelectorAll('.mon-spark span');
    expect(bars[0].style.height).toBe('2px');
  });
});

describe('monitor time formats', () => {
  const now = Date.parse('2026-07-26T12:00:00Z');

  it('formats how long ago a check landed', () => {
    expect(formatAgo(null, now)).toBe('—');
    expect(formatAgo('2026-07-26T11:59:56Z', now)).toBe('4s ago');
    expect(formatAgo('2026-07-26T11:57:00Z', now)).toBe('3m ago');
    expect(formatAgo('2026-07-26T10:00:00Z', now)).toBe('2h ago');
    expect(formatAgo('2026-07-21T12:00:00Z', now)).toBe('5d ago');
  });

  it('formats time spent in the current state', () => {
    expect(formatSince(null, now)).toBe('—');
    expect(formatSince('2026-07-26T11:59:18Z', now)).toBe('42s');
    expect(formatSince('2026-07-26T11:53:48Z', now)).toBe('6m 12s');
    expect(formatSince('2026-07-26T08:56:00Z', now)).toBe('3h 04m');
    expect(formatSince('2026-07-24T07:00:00Z', now)).toBe('2d 5h');
  });
});
