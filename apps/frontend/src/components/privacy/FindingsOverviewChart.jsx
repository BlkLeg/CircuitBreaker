import React, { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

/**
 * Findings Overview — stacked area chart showing Warning vs Info findings over time.
 *
 * Data is derived client-side from the snapshot history. Each snapshot only has
 * {score, at} today, so we use the current snapshot's deduction breakdown as the
 * latest data point and show what we have. As more snapshots accumulate with
 * deduction data, the chart gets richer.
 */
export default function FindingsOverviewChart({ deductions, history }) {
  const chartData = useMemo(() => {
    if (!history?.length) return [];

    // Build a single-point from current deductions for the latest snapshot
    const currentWarnings = (deductions || []).filter((d) => d.severity === 'warning').length;
    const currentInfos = (deductions || []).filter((d) => d.severity === 'info').length;
    const currentCritical = (deductions || []).filter((d) => d.severity === 'critical').length;

    // Use history to build time axis; only the latest point has severity data
    const points = [...history].reverse();
    return points.map((p, i) => {
      const isLatest = i === points.length - 1;
      return {
        date: p.at
          ? new Date(p.at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
          : '',
        warning: isLatest ? currentWarnings + currentCritical : null,
        info: isLatest ? currentInfos : null,
        // Interpolate zeros for earlier points so the chart has shape
        ...(isLatest ? {} : { warning: 0, info: 0 }),
      };
    });
  }, [deductions, history]);

  if (chartData.length < 1) return null;

  return (
    <div className="card privacy-card" style={{ padding: 20 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600 }}>Findings Overview</div>
        <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: '#eab308',
                display: 'inline-block',
              }}
            />
            Warning
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: '#3b82f6',
                display: 'inline-block',
              }}
            />
            Info
          </span>
        </div>
      </div>
      <div style={{ height: 180 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="warningGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#eab308" stopOpacity={0.35} />
                <stop offset="95%" stopColor="#eab308" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="infoGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.35} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--color-grid-line, rgba(255,255,255,0.06))"
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: 'var(--color-text-muted, #6b7280)' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 10, fill: 'var(--color-text-muted, #6b7280)' }}
              axisLine={false}
              tickLine={false}
              width={30}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--color-surface, #1e1e1e)',
                border: '1px solid var(--color-border, #333)',
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Area
              type="monotone"
              dataKey="warning"
              stackId="1"
              stroke="#eab308"
              strokeWidth={2}
              fill="url(#warningGrad)"
              dot={false}
            />
            <Area
              type="monotone"
              dataKey="info"
              stackId="1"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="url(#infoGrad)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
