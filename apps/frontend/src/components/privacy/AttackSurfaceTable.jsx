import React, { useMemo, useState } from 'react';
import { Monitor } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function AttackSurfaceTable({ attackSurface }) {
  const navigate = useNavigate();
  const [sortKey, setSortKey] = useState('name');
  const [sortAsc, setSortAsc] = useState(true);

  const sorted = useMemo(() => {
    if (!attackSurface) return [];
    const rows = [...attackSurface];
    rows.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'name') cmp = (a.name || '').localeCompare(b.name || '');
      else if (sortKey === 'ip') cmp = (a.ip_address || '').localeCompare(b.ip_address || '');
      else if (sortKey === 'ports') cmp = (a.ports?.length || 0) - (b.ports?.length || 0);
      return sortAsc ? cmp : -cmp;
    });
    return rows;
  }, [attackSurface, sortKey, sortAsc]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const sortIndicator = (key) => {
    if (sortKey !== key) return ' ⇅';
    return sortAsc ? ' ↑' : ' ↓';
  };

  const thStyle = {
    padding: '12px 16px',
    borderBottom: '1px solid var(--color-border)',
    textAlign: 'left',
    fontWeight: 600,
  };
  const tdStyle = {
    padding: '12px 16px',
    verticalAlign: 'top',
  };

  if (!attackSurface || attackSurface.length === 0) {
    return (
      <div className="card privacy-card" style={{ padding: 20 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Attack Surface</div>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
          No open ports detected on any scanned devices.
        </p>
      </div>
    );
  }

  return (
    <div className="card privacy-card" style={{ padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Attack Surface</div>
      <div style={{ overflowX: 'auto' }}>
        <table
          style={{ width: '100%', fontSize: 13, borderCollapse: 'separate', borderSpacing: 0 }}
        >
          <thead>
            <tr
              style={{
                color: 'var(--color-text-muted)',
                fontSize: 11,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              <th
                style={{ ...thStyle, cursor: 'pointer', width: '25%' }}
                onClick={() => toggleSort('name')}
              >
                Device {sortIndicator('name')}
              </th>
              <th
                style={{ ...thStyle, cursor: 'pointer', width: '20%' }}
                onClick={() => toggleSort('ip')}
              >
                IP Address {sortIndicator('ip')}
              </th>
              <th style={{ ...thStyle, cursor: 'pointer' }} onClick={() => toggleSort('ports')}>
                Open Ports {sortIndicator('ports')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.hardware_id}
                style={{
                  borderBottom: '1px solid var(--color-border)',
                  transition: 'background 0.1s',
                }}
              >
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Monitor size={14} color="var(--color-primary)" />
                    <span
                      style={{ cursor: 'pointer', color: 'var(--color-primary)', fontWeight: 500 }}
                      onClick={() => navigate('/hardware')}
                      title="Open Hardware page"
                    >
                      {row.name || `Hardware #${row.hardware_id}`}
                    </span>
                  </div>
                </td>
                <td style={tdStyle}>
                  {row.ip_address ? (
                    <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{row.ip_address}</span>
                  ) : (
                    <span style={{ color: 'var(--color-text-muted)' }}>—</span>
                  )}
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {row.ports && row.ports.length > 0 ? (
                      row.ports.map((p, idx) => {
                        const portNum = p.port || p;
                        const proto = p.proto || p.protocol || 'tcp';
                        const service = p.service || p.name || '';
                        return (
                          <div
                            key={idx}
                            style={{
                              padding: '4px 8px',
                              borderRadius: 6,
                              fontSize: 11,
                              background: 'var(--color-surface-hover, rgba(255,255,255,0.05))',
                              border: '1px solid var(--color-border, #333)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 6,
                              whiteSpace: 'nowrap',
                            }}
                          >
                            <span
                              style={{
                                fontFamily: 'monospace',
                                fontWeight: 600,
                                color: 'var(--color-primary, #60a5fa)',
                              }}
                            >
                              {portNum}/{proto}
                            </span>
                            {service && <span style={{ opacity: 0.8 }}>{service}</span>}
                          </div>
                        );
                      })
                    ) : (
                      <span style={{ color: 'var(--color-text-muted)' }}>—</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
