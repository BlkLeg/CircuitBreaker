import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }) => <div data-testid="chart">{children}</div>,
  LineChart: ({ children }) => <div>{children}</div>,
  Line: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}));

import LatencyChart from '../components/monitors/LatencyChart.jsx';

describe('LatencyChart', () => {
  it('explains itself when there is not enough data', () => {
    render(<LatencyChart points={[{ ts: '2026-07-26T00:00:00Z', value: 5 }]} />);
    expect(screen.getByText('Not enough data yet.')).toBeTruthy();
  });

  it('renders a chart once there are two points', () => {
    render(
      <LatencyChart
        points={[
          { ts: '2026-07-26T00:00:00Z', value: 5 },
          { ts: '2026-07-26T00:01:00Z', value: 7 },
        ]}
      />
    );
    expect(screen.getByTestId('chart')).toBeTruthy();
  });
});
