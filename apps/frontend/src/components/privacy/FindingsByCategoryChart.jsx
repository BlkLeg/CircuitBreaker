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
 * Static mapping from rule_id to a display category.
 * Network-check rules map to DNS; device rules map to Protocols.
 */
const RULE_CATEGORY = {
  dns_tamper: 'DNS',
  dns_filtering_absent: 'DNS',
  captive_portal: 'DNS',
  telnet_open: 'Protocols',
  ftp_open: 'Protocols',
  legacy_smb_netbios: 'Protocols',
  upnp_exposed: 'Protocols',
};

const ALL_CATEGORIES = ['DNS', 'Protocols', 'Devices', 'Scans', 'Companies', 'Others'];

const CATEGORY_COLORS = [
  '#22c55e', // DNS — green
  '#3b82f6', // Protocols — blue
  '#a855f7', // Devices — purple
  '#eab308', // Scans — amber
  '#f97316', // Companies — orange
  '#64748b', // Others — slate
];

export default function FindingsByCategoryChart({ deductions }) {
  const chartData = useMemo(() => {
    const counts = {};
    ALL_CATEGORIES.forEach((c) => (counts[c] = 0));

    (deductions || []).forEach((d) => {
      const cat = RULE_CATEGORY[d.rule_id];
      if (cat) {
        counts[cat]++;
      } else if (d.hardware_id != null) {
        counts['Devices']++;
      } else {
        counts['Others']++;
      }
    });

    return ALL_CATEGORIES.map((name, idx) => ({
      name,
      count: counts[name],
      color: CATEGORY_COLORS[idx],
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
