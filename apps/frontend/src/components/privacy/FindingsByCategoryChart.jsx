/* eslint-disable security/detect-object-injection */
import React, { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

/**
 * Category display labels/colors, keyed by the backend's rule `category` field
 * (see DEVICE_RULES / NETWORK_CHECK_RULES in privacy_rules.py). 'other' is a
 * fallback bucket for any deduction that somehow lacks a recognized category.
 */
const CATEGORY_LABELS = {
  dns: 'DNS',
  protocols: 'Protocols',
  services: 'Services',
  network: 'Network',
  other: 'Other',
};

const CATEGORY_COLORS = {
  dns: '#22c55e',
  protocols: '#3b82f6',
  services: '#a855f7',
  network: '#eab308',
  other: '#64748b',
};

const ALL_CATEGORIES = ['dns', 'protocols', 'services', 'network', 'other'];

export default function FindingsByCategoryChart({ deductions }) {
  const chartData = useMemo(() => {
    const counts = {};
    ALL_CATEGORIES.forEach((c) => (counts[c] = 0));

    (deductions || []).forEach((d) => {
      const cat = CATEGORY_LABELS[d.category] ? d.category : 'other';
      counts[cat]++;
    });

    return ALL_CATEGORIES.map((key) => ({
      name: CATEGORY_LABELS[key],
      count: counts[key],
      color: CATEGORY_COLORS[key],
    }));
  }, [deductions]);

  const hasData = chartData.some((d) => d.count > 0);

  return (
    <div className="card privacy-card" style={{ padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Findings by Category</div>
      {hasData ? (
        <div style={{ height: 180 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 4, right: 20, left: 10, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--color-grid-line, rgba(255,255,255,0.06))"
                horizontal={false}
              />
              <XAxis
                type="number"
                allowDecimals={false}
                tick={{ fontSize: 10, fill: 'var(--color-text-muted, #6b7280)' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                dataKey="name"
                type="category"
                tick={{ fontSize: 12, fill: 'var(--color-text, #e5e5e5)' }}
                axisLine={false}
                tickLine={false}
                width={80}
              />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface, #1e1e1e)',
                  border: '1px solid var(--color-border, #333)',
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(value) => [`${value}`, 'Findings']}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={16}>
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div
          style={{
            fontSize: 13,
            color: 'var(--color-text-muted)',
            padding: '30px 0',
            textAlign: 'center',
          }}
        >
          No findings to categorize.
        </div>
      )}
    </div>
  );
}
