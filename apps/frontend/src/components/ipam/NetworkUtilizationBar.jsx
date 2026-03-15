/**
 * NetworkUtilizationBar — stacked bar showing IP status distribution.
 * Reusable in SubnetTab, NetworksPage, NetworkDetail drawer.
 */
import React from 'react';
import PropTypes from 'prop-types';

const SEGMENTS = [
  { key: 'allocated', color: '#22c55e', label: 'Allocated' },
  { key: 'reserved', color: '#f59e0b', label: 'Reserved' },
  { key: 'dhcp', color: '#a78bfa', label: 'DHCP' },
  { key: 'free_tracked', color: '#3b82f6', label: 'Free' },
  { key: 'untracked', color: '#374151', label: 'Untracked' },
];

export default function NetworkUtilizationBar({ data }) {
  if (!data) return null;
  const total = data.total_hosts || 1;

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{data.cidr}</span>
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          {data.utilization_pct}% utilized — {data.allocated} / {total} hosts
        </span>
      </div>

      {/* Stacked bar */}
      <div
        style={{
          height: 20,
          display: 'flex',
          borderRadius: 4,
          overflow: 'hidden',
          background: '#1f2937',
          border: '1px solid var(--color-border)',
        }}
      >
        {SEGMENTS.map(({ key, color }) => {
          const val = data[key] || 0;
          if (val === 0) return null;
          return (
            <div
              key={key}
              title={`${key}: ${val}`}
              style={{
                width: `${(val / total) * 100}%`,
                background: color,
                minWidth: val > 0 ? 2 : 0,
              }}
            />
          );
        })}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
        {SEGMENTS.map(({ key, color, label }) => {
          const val = data[key] || 0;
          if (val === 0) return null;
          return (
            <span key={key} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  background: color,
                  display: 'inline-block',
                }}
              />
              {label}: {val}
            </span>
          );
        })}
      </div>
    </div>
  );
}

NetworkUtilizationBar.propTypes = {
  data: PropTypes.object,
};
