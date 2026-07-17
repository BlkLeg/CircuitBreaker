import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Monitor } from 'lucide-react';
import { windscribeApi } from '../../api/client';

const SEVERITY_COLORS = {
  critical: 'var(--color-danger, #ef4444)',
  warning: 'var(--color-warning, #eab308)',
  info: 'var(--color-info, #3b82f6)',
};

/**
 * Enhanced flagged devices table with OS column, Remediate/Ignore actions,
 * and sortable columns.
 */
export default function FlaggedDevicesTable({ deductions, hardwareMap, onRemediate }) {
  const navigate = useNavigate();
  const [sortKey, setSortKey] = useState('points');
  const [sortAsc, setSortAsc] = useState(false);
  const [ignored, setIgnored] = useState(new Map());

  useEffect(() => {
    let cancelled = false;
    windscribeApi
      .getIgnoredFindings()
      .then((res) => {
        if (cancelled) return;
        const seeded = new Map();
        for (const { rule_id, hardware_id } of res.data?.ignores || []) {
          seeded.set(`${rule_id}-${hardware_id}`, { ruleId: rule_id, hardwareId: hardware_id });
        }
        setIgnored(seeded);
      })
      .catch((err) => console.error('Failed to load ignored findings:', err));
    return () => {
      cancelled = true;
    };
  }, []);

  const handleIgnore = (row) => {
    const key = row.key;
    setIgnored((prev) =>
      new Map(prev).set(key, { ruleId: row.deduction.rule_id, hardwareId: row.hardwareId })
    );
    windscribeApi
      .ignoreFinding(row.deduction.rule_id, row.hardwareId)
      .catch((err) => console.error('Failed to ignore finding:', err));
  };

  const handleShowAll = () => {
    const entries = [...ignored.values()];
    setIgnored(new Map());
    for (const { ruleId, hardwareId } of entries) {
      windscribeApi
        .unignoreFinding(ruleId, hardwareId)
        .catch((err) => console.error('Failed to unignore finding:', err));
    }
  };

  const byDevice = useMemo(() => {
    const map = new Map();
    for (const d of deductions || []) {
      if (d.hardware_id == null) continue;
      if (!map.has(d.hardware_id)) map.set(d.hardware_id, []);
      map.get(d.hardware_id).push(d);
    }

    // Flatten into rows for the table
    const rows = [];
    for (const [hwId, items] of map.entries()) {
      const hw = hardwareMap?.get(hwId);
      for (const d of items) {
        rows.push({
          key: `${d.rule_id}-${hwId}`,
          hardwareId: hwId,
          deviceName: hw?.name || `Hardware #${hwId}`,
          os: hw?.os || null,
          iconSlug: hw?.icon_slug || null,
          finding: d.title,
          points: d.points,
          severity: d.severity,
          deduction: d,
        });
      }
    }
    return rows;
  }, [deductions, hardwareMap]);

  const sorted = useMemo(() => {
    const rows = byDevice.filter((r) => !ignored.has(r.key));
    rows.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'points') cmp = a.points - b.points;
      else if (sortKey === 'name') cmp = a.deviceName.localeCompare(b.deviceName);
      else if (sortKey === 'finding') cmp = a.finding.localeCompare(b.finding);
      return sortAsc ? cmp : -cmp;
    });
    return rows;
  }, [byDevice, sortKey, sortAsc, ignored]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sortIndicator = (key) => {
    if (sortKey !== key) return ' ⇅';
    return sortAsc ? ' ↑' : ' ↓';
  };

  if (!byDevice.length) {
    return (
      <div className="card privacy-card" style={{ padding: 20 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Flagged Devices</div>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
          No devices are currently flagged.
        </p>
      </div>
    );
  }

  return (
    <div className="card privacy-card" style={{ padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Flagged Devices</div>
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
              <th style={{ ...thStyle, cursor: 'pointer' }} onClick={() => toggleSort('name')}>
                Device Name{sortIndicator('name')}
              </th>
              <th style={thStyle}>OS</th>
              <th style={{ ...thStyle, cursor: 'pointer' }} onClick={() => toggleSort('finding')}>
                Finding{sortIndicator('finding')}
              </th>
              <th
                style={{ ...thStyle, textAlign: 'right', cursor: 'pointer' }}
                onClick={() => toggleSort('points')}
              >
                Points{sortIndicator('points')}
              </th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.key}
                style={{
                  borderBottom: '1px solid var(--color-border, #333)',
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
                      {row.deviceName}
                    </span>
                  </div>
                </td>
                <td style={tdStyle}>
                  {row.os ? (
                    <span style={{ fontSize: 12, opacity: 0.8 }} title={row.os}>
                      {row.os}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--color-text-muted)' }}>—</span>
                  )}
                </td>
                <td style={tdStyle}>
                  <span>{row.finding}</span>
                </td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: 'right',
                    color: SEVERITY_COLORS[row.severity],
                    fontWeight: 600,
                  }}
                >
                  −{row.points}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button
                      className="btn"
                      style={actionBtnStyle('var(--color-primary, #00f5ff)')}
                      onClick={() => onRemediate?.(row.deduction)}
                    >
                      Remediate
                    </button>
                    <button
                      className="btn"
                      style={actionBtnStyle('var(--color-text-muted, #6b7280)')}
                      onClick={() => handleIgnore(row)}
                    >
                      Ignore
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ignored.size > 0 && (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--color-text-muted)' }}>
          {ignored.size} finding(s) ignored.{' '}
          <button
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--color-primary)',
              cursor: 'pointer',
              fontSize: 11,
              textDecoration: 'underline',
              padding: 0,
            }}
            onClick={handleShowAll}
          >
            Show all
          </button>
        </div>
      )}
    </div>
  );
}

const thStyle = {
  textAlign: 'left',
  padding: '8px 10px',
  fontWeight: 600,
  borderBottom: '1px solid var(--color-border, #333)',
  whiteSpace: 'nowrap',
};

const tdStyle = {
  padding: '10px 10px',
  borderBottom: '1px solid var(--color-border, rgba(255,255,255,0.05))',
  verticalAlign: 'middle',
};

function actionBtnStyle(color) {
  return {
    fontSize: 11,
    padding: '4px 10px',
    borderRadius: 6,
    border: `1px solid ${color}`,
    background: 'transparent',
    color,
    cursor: 'pointer',
    fontWeight: 600,
    whiteSpace: 'nowrap',
  };
}
