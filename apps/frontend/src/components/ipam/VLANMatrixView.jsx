/**
 * VLANMatrixView — grid: rows=VLANs, cols=hardware, cells=trunk membership.
 */
import React, { useState, useEffect } from 'react';
import { ipamApi } from '../../api/client';

export default function VLANMatrixView() {
  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    ipamApi
      .vlanMatrix()
      .then((r) => setMatrix(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p style={{ color: 'var(--color-text-muted)' }}>Loading matrix…</p>;
  if (!matrix || matrix.vlans.length === 0 || matrix.hardware.length === 0) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontStyle: 'italic', fontSize: 13 }}>
        No data for matrix view. Add VLANs and trunk assignments first.
      </p>
    );
  }

  const cellStyle = (mode) => ({
    width: 28,
    height: 28,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 10,
    fontWeight: 600,
    borderRadius: 3,
    background: mode === 'tagged' ? '#3b82f620' : mode === 'untagged' ? '#f59e0b20' : 'transparent',
    color: mode === 'tagged' ? '#3b82f6' : mode === 'untagged' ? '#f59e0b' : 'var(--color-border)',
    border: `1px solid ${mode ? 'var(--color-border)' : 'transparent'}`,
  });

  return (
    <div style={{ overflow: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            <th style={{ padding: '4px 8px', textAlign: 'left' }}>VLAN</th>
            {matrix.hardware.map((h) => (
              <th
                key={h.id}
                style={{
                  padding: '4px 4px',
                  textAlign: 'center',
                  whiteSpace: 'nowrap',
                  maxWidth: 80,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  fontSize: 11,
                }}
                title={h.name}
              >
                {h.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.vlans.map((v) => (
            <tr key={v.id}>
              <td style={{ padding: '4px 8px', fontWeight: 600, whiteSpace: 'nowrap' }}>
                {v.vlan_id}
                {v.name ? ` ${v.name}` : ''}
              </td>
              {matrix.hardware.map((h) => {
                const mode = matrix.matrix[`${v.id},${h.id}`];
                return (
                  <td key={h.id} style={{ padding: 2, textAlign: 'center' }}>
                    <div style={cellStyle(mode)}>
                      {mode === 'tagged' ? 'T' : mode === 'untagged' ? 'U' : '·'}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 11 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: 2,
              background: '#3b82f620',
              border: '1px solid #3b82f6',
            }}
          />
          Tagged
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: 2,
              background: '#f59e0b20',
              border: '1px solid #f59e0b',
            }}
          />
          Untagged
        </span>
      </div>
    </div>
  );
}
