import React from 'react';
import PropTypes from 'prop-types';
import { CONNECTION_STYLES_MAP } from '../../config/mapTheme';
import { CONNECTION_TYPE_OPTIONS, normalizeConnectionType } from './connectionTypes';

function ConnectionTypePicker({ x, y, defaultConnectionType, onSelect, onCancel }) {
  const left = Math.max(8, x);
  const top = Math.max(8, y);
  const normalizedDefault = normalizeConnectionType(defaultConnectionType) || 'ethernet';
  const isDefault = (type) =>
    type === normalizedDefault || normalizeConnectionType(type) === normalizedDefault;

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
      {defaultConnectionType && (
        <div
          style={{
            fontSize: 10,
            color: 'var(--color-text-muted)',
            marginBottom: 8,
            textAlign: 'center',
          }}
        >
          Previous: <strong style={{ color: 'var(--color-text)' }}>{normalizedDefault}</strong>
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
        {CONNECTION_TYPE_OPTIONS.map((type) => {
          const cs = CONNECTION_STYLES_MAP.get(type);
          const selected = isDefault(type);
          return (
            <button
              key={type}
              onClick={() => onSelect(type)}
              style={{
                padding: '7px 6px',
                borderRadius: 6,
                border: `2px solid ${selected ? cs?.stroke || 'var(--color-primary)' : cs?.stroke || '#555'}`,
                background: selected
                  ? `${cs?.stroke || 'var(--color-primary)'}22`
                  : 'var(--color-surface-secondary)',
                color: cs?.stroke || '#ccc',
                fontSize: 10,
                fontWeight: selected ? 700 : 600,
                cursor: 'pointer',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                transition: 'background 0.12s, border-color 0.12s',
              }}
              title={selected ? 'Same as previous connection' : undefined}
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
  defaultConnectionType: PropTypes.string,
  onSelect: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default ConnectionTypePicker;
