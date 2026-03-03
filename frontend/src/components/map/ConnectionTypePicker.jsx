import React from 'react';
import PropTypes from 'prop-types';
import { CONNECTION_STYLES } from '../../config/mapTheme';
import { CONNECTION_TYPE_OPTIONS } from './connectionTypes';

function ConnectionTypePicker({ x, y, onSelect, onCancel }) {
  const left = Math.max(8, x);
  const top = Math.max(8, y);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Connection type picker"
      style={{
        position: 'absolute',
        left,
        top,
        zIndex: 1000,
        background: 'var(--color-surface)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderRadius: 10,
        border: '1px solid var(--color-border)',
        padding: '14px 18px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        minWidth: 220,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        style={{
          fontSize: 11,
          color: 'var(--color-text-muted)',
          marginBottom: 10,
          textAlign: 'center',
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          fontWeight: 600,
        }}
      >
        Select connection type
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
        {CONNECTION_TYPE_OPTIONS.map((type) => {
          const cs = CONNECTION_STYLES[type];
          return (
            <button
              key={type}
              onClick={() => onSelect(type)}
              style={{
                padding: '7px 6px',
                borderRadius: 6,
                border: `1px solid ${cs?.stroke || '#555'}`,
                background: 'var(--color-surface-secondary)',
                color: cs?.stroke || '#ccc',
                fontSize: 10,
                fontWeight: 700,
                cursor: 'pointer',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                transition: 'background 0.12s',
              }}
            >
              {type}
            </button>
          );
        })}
      </div>
      <button
        onClick={onCancel}
        style={{
          marginTop: 10,
          width: '100%',
          padding: '4px 0',
          border: '1px solid rgba(255,255,255,0.12)',
          background: 'var(--color-surface-secondary)',
          borderRadius: 4,
          color: 'var(--color-text-muted)',
          fontSize: 10,
          cursor: 'pointer',
        }}
      >
        Cancel
      </button>
    </div>
  );
}

ConnectionTypePicker.propTypes = {
  x: PropTypes.number.isRequired,
  y: PropTypes.number.isRequired,
  onSelect: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default ConnectionTypePicker;
