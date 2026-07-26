import React from 'react';
import PropTypes from 'prop-types';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

/**
 * LatencyChart — latency series for one monitor. Shared by the monitors
 * dashboard's expanded cards and the monitor detail page.
 */
export default function LatencyChart({ points = [], height = 160 }) {
  if (points.length < 2) return <p className="text-muted">Not enough data yet.</p>;
  const data = points.map((p) => ({ ts: new Date(p.ts).getTime(), value: p.value }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis
          dataKey="ts"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(t) => new Date(t).toLocaleTimeString()}
          stroke="var(--color-text-muted)"
          fontSize={11}
        />
        <YAxis
          stroke="var(--color-text-muted)"
          fontSize={11}
          tickFormatter={(v) => `${Math.round(v)}`}
          width={40}
        />
        <Tooltip
          labelFormatter={(t) => new Date(t).toLocaleString()}
          formatter={(v) => [`${Math.round(v)} ms`, 'Latency']}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke="var(--color-primary)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

LatencyChart.propTypes = {
  points: PropTypes.arrayOf(PropTypes.object),
  height: PropTypes.number,
};
