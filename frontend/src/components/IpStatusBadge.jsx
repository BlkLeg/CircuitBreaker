import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { AlertTriangle } from 'lucide-react';

const ENTITY_LABELS = { hardware: 'Hardware', compute_unit: 'Compute Unit', service: 'Service' };

function IpStatusBadge({ ipMode, conflictWith, flash, onOpenEntity }) {
  const [isFlashing, setIsFlashing] = useState(false);
  const prevFlash = useRef(false);

  useEffect(() => {
    if (flash && !prevFlash.current) {
      setIsFlashing(true);
      const t = setTimeout(() => setIsFlashing(false), 800);
      return () => clearTimeout(t);
    }
    prevFlash.current = flash;
  }, [flash]);

  if (
    ipMode === 'inherited_from_compute' ||
    ipMode === 'inherited_from_hardware' ||
    ipMode === 'inherited_from_hardware_via_compute'
  ) {
    const label = ipMode === 'inherited_from_compute' ? 'compute unit' : 'host hardware';
    return (
      <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--color-text-muted, #9ca3af)' }}>
        ℹ Inherited from {label}. No conflict.
      </p>
    );
  }

  if (ipMode === 'explicit' && conflictWith?.length > 0) {
    return (
      <div style={{
        marginTop: 8, padding: '10px 14px',
        background: isFlashing ? '#7a4d00' : 'var(--color-surface, #1e1e2e)',
        border: `1.5px solid ${isFlashing ? '#f59e0b' : '#d97706'}`,
        borderRadius: 6, transition: 'background 0.15s ease, border-color 0.15s ease',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
          <AlertTriangle size={15} style={{ color: '#f59e0b', flexShrink: 0 }} />
          <span style={{ fontWeight: 600, fontSize: 13, color: '#f59e0b' }}>IP conflict detected</span>
        </div>
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 5 }}>
          {conflictWith.map((c) => (
            <li key={`${c.entity_type}-${c.entity_id}`}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12, color: 'var(--color-text-muted, #9ca3af)' }}>
                <code style={{ color: '#fcd34d', fontSize: 11 }}>{c.entity_ip}</code>
                {' '}is already assigned to{' '}
                <strong style={{ color: 'var(--color-text, #e5e7eb)' }}>{c.entity_name}</strong>
                {' '}
                <span style={{ color: '#6b7280' }}>({ENTITY_LABELS[c.entity_type] || c.entity_type})</span>
              </span>
              {c.entity_id != null && (
                <button type="button" onClick={() => onOpenEntity?.(c)}
                  style={{ flexShrink: 0, fontSize: 11, color: '#60a5fa', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px', borderRadius: 4, textDecoration: 'underline', whiteSpace: 'nowrap' }}>
                  Open →
                </button>
              )}
            </li>
          ))}
        </ul>
        <p style={{ margin: '8px 0 0', fontSize: 11, color: '#9ca3af' }}>
          Change the address or resolve the conflicts before saving.
        </p>
      </div>
    );
  }

  return null;
}

IpStatusBadge.propTypes = {
  ipMode: PropTypes.string,
  conflictWith: PropTypes.array,
  flash: PropTypes.bool,
  onOpenEntity: PropTypes.func,
};

export default IpStatusBadge;
