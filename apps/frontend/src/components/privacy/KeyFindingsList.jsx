/* eslint-disable security/detect-object-injection */
import React, { useMemo, useState, useRef, useEffect } from 'react';

const SEVERITY_ORDER = ['critical', 'warning', 'info'];
const SEVERITY_COLORS = {
  critical: 'var(--color-danger, #ef4444)',
  warning: 'var(--color-warning, #eab308)',
  info: 'var(--color-info, #3b82f6)',
};

function ContextMenu({ x, y, onAction, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div
      ref={ref}
      style={{
        position: 'fixed',
        left: x,
        top: y,
        zIndex: 300,
        background: 'var(--color-surface, #1e1e1e)',
        border: '1px solid var(--color-border, #333)',
        borderRadius: 8,
        boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
        padding: 4,
        minWidth: 140,
      }}
    >
      <button className="btn" style={menuItemStyle} onClick={() => onAction('details')}>
        View Details
      </button>
      <button className="btn" style={menuItemStyle} onClick={() => onAction('remediate')}>
        Remediate
      </button>
    </div>
  );
}

const menuItemStyle = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  padding: '8px 12px',
  fontSize: 13,
  border: 'none',
  background: 'transparent',
  color: 'var(--color-text)',
  borderRadius: 6,
  cursor: 'pointer',
};

export default function KeyFindingsList({ deductions, onRemediate, onViewDetails }) {
  const [contextMenu, setContextMenu] = useState(null);

  const grouped = useMemo(() => {
    const groups = { critical: [], warning: [], info: [] };
    for (const d of deductions || []) (groups[d.severity] || groups.info).push(d);
    return groups;
  }, [deductions]);

  const handleContextMenu = (e, deduction) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, deduction });
  };

  const handleAction = (action) => {
    if (!contextMenu) return;
    if (action === 'remediate') onRemediate?.(contextMenu.deduction);
    if (action === 'details') onViewDetails?.(contextMenu.deduction);
    setContextMenu(null);
  };

  if (!deductions?.length) {
    return (
      <div className="card privacy-card" style={{ padding: 20 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Key Findings List</div>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
          No findings — nothing to remediate.
        </p>
      </div>
    );
  }

  return (
    <div className="card privacy-card" style={{ padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Key Findings List</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {SEVERITY_ORDER.filter((severity) => grouped[severity].length).map((severity) => (
          <div key={severity}>
            <div
              style={{
                fontSize: 12,
                fontWeight: 700,
                textTransform: 'capitalize',
                color: SEVERITY_COLORS[severity],
                marginBottom: 8,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {severity} ({grouped[severity].length})
            </div>
            {grouped[severity].map((deduction, i) => (
              <div
                key={`${deduction.rule_id}-${deduction.hardware_id ?? 'net'}-${i}`}
                onContextMenu={(e) => handleContextMenu(e, deduction)}
                onClick={() => onRemediate?.(deduction)}
                style={{
                  display: 'flex',
                  width: '100%',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '10px 14px',
                  marginBottom: 6,
                  borderRadius: 8,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface-alt, var(--color-surface))',
                  cursor: 'pointer',
                  transition: 'background 0.15s ease',
                  borderLeft: `3px solid ${SEVERITY_COLORS[severity]}`,
                }}
              >
                <span style={{ fontSize: 13, color: 'var(--color-text)' }}>
                  {deduction.title} (−{deduction.points} points)
                </span>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: SEVERITY_COLORS[severity],
                    minWidth: 30,
                    textAlign: 'right',
                  }}
                >
                  −{deduction.points}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onAction={handleAction}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  );
}
