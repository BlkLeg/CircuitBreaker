/**
 * SubnetHeatmap — color-coded grid of IPs or /24 blocks.
 * Green=allocated, Blue=free, Yellow=reserved, Purple=dhcp, Red=conflict, Gray=untracked.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';

const STATUS_COLORS = {
  allocated: '#22c55e',
  free: '#3b82f6',
  reserved: '#f59e0b',
  dhcp: '#a78bfa',
  conflict: '#ef4444',
  untracked: '#374151',
};

const LEGEND = Object.entries(STATUS_COLORS);

function Tooltip({ text, children }) {
  const [show, setShow] = useState(false);
  return (
    <span
      style={{ position: 'relative' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            background: '#1f2937',
            color: '#f9fafb',
            padding: '4px 8px',
            borderRadius: 4,
            fontSize: 11,
            whiteSpace: 'nowrap',
            zIndex: 10,
            pointerEvents: 'none',
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

export default function SubnetHeatmap({ data }) {
  if (!data || data.length === 0) return null;

  // Detect mode: individual IPs or /24 blocks
  const isBlock = data[0]?.block !== undefined;

  return (
    <div>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        {LEGEND.map(([status, color]) => (
          <span
            key={status}
            style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}
          >
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: 2,
                background: color,
                display: 'inline-block',
              }}
            />
            {status}
          </span>
        ))}
      </div>

      {isBlock ? (
        /* /24 block view */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {data.map((block) => {
            const total = block.total || 1;
            const pct = (v) => `${Math.round((v / total) * 100)}%`;
            return (
              <div key={block.block} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, width: 140, fontFamily: 'monospace' }}>
                  {block.block}
                </span>
                <div
                  style={{
                    flex: 1,
                    height: 16,
                    display: 'flex',
                    borderRadius: 3,
                    overflow: 'hidden',
                    background: STATUS_COLORS.untracked,
                  }}
                >
                  {block.allocated > 0 && (
                    <div
                      style={{ width: pct(block.allocated), background: STATUS_COLORS.allocated }}
                    />
                  )}
                  {block.reserved > 0 && (
                    <div
                      style={{ width: pct(block.reserved), background: STATUS_COLORS.reserved }}
                    />
                  )}
                  {block.dhcp > 0 && (
                    <div style={{ width: pct(block.dhcp), background: STATUS_COLORS.dhcp }} />
                  )}
                  {block.free > 0 && (
                    <div style={{ width: pct(block.free), background: STATUS_COLORS.free }} />
                  )}
                </div>
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--color-text-muted)',
                    width: 40,
                    textAlign: 'right',
                  }}
                >
                  {block.total}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        /* Individual IP grid */
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(16, 1fr)',
            gap: 2,
          }}
        >
          {data.map((ip) => (
            <Tooltip
              key={ip.ip}
              text={`${ip.ip} — ${ip.status}${ip.hostname ? ` (${ip.hostname})` : ''}`}
            >
              <div
                style={{
                  width: '100%',
                  aspectRatio: '1',
                  borderRadius: 2,
                  background: STATUS_COLORS[ip.status] ?? STATUS_COLORS.untracked,
                  cursor: 'pointer',
                  minWidth: 8,
                }}
              />
            </Tooltip>
          ))}
        </div>
      )}
    </div>
  );
}

SubnetHeatmap.propTypes = {
  data: PropTypes.array,
};
