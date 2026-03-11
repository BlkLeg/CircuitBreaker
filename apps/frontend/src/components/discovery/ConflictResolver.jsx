/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useState } from 'react';
import PropTypes from 'prop-types';

/**
 * ConflictResolver
 *
 * Renders a two-column table with radio buttons per conflicting field.
 * Default: 'keep existing' for all rows (conservative).
 * Calls onChange with only the fields where 'use discovered' was selected.
 */
export default function ConflictResolver({ conflicts, onChange }) {
  // State: map of field → 'existing' | 'discovered'
  const [selections, setSelections] = useState(() =>
    Object.fromEntries(conflicts.map((c) => [c.field, 'existing']))
  );

  if (!conflicts || conflicts.length === 0) return null;

  const handleChange = (field, choice) => {
    const next = { ...selections, [field]: choice };
    setSelections(next);

    // Build overrides — only fields where 'use discovered' was selected
    const overrides = {};
    conflicts.forEach(({ field: f, discovered }) => {
      if (next[f] === 'discovered') {
        overrides[f] = discovered;
      }
    });
    onChange(overrides);
  };

  return (
    <div>
      <div
        style={{
          padding: '10px 14px',
          background: 'rgba(245,158,11,0.1)',
          border: '1px solid rgba(245,158,11,0.3)',
          borderRadius: 6,
          marginBottom: 16,
          fontSize: 12,
          color: '#fbbf24',
        }}
      >
        ⚠️ This host matches an existing device but some data differs. Choose which values to keep.
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            <th style={thStyle}>Field</th>
            <th style={thStyle}>Current (stored)</th>
            <th style={thStyle}>Discovered</th>
          </tr>
        </thead>
        <tbody>
          {conflicts.map(({ field, stored, discovered }) => (
            <tr key={field} style={{ borderBottom: '1px solid var(--color-border)' }}>
              <td style={tdStyle}>
                <code style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{field}</code>
              </td>
              <td style={tdStyle}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name={field}
                    value="existing"
                    checked={selections[field] === 'existing'}
                    onChange={() => handleChange(field, 'existing')}
                  />
                  <span
                    style={{
                      color:
                        selections[field] === 'existing'
                          ? 'var(--color-text)'
                          : 'var(--color-text-muted)',
                    }}
                  >
                    {String(stored ?? '—')}
                  </span>
                </label>
              </td>
              <td style={tdStyle}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name={field}
                    value="discovered"
                    checked={selections[field] === 'discovered'}
                    onChange={() => handleChange(field, 'discovered')}
                  />
                  <span
                    style={{
                      color:
                        selections[field] === 'discovered'
                          ? 'var(--color-primary)'
                          : 'var(--color-text-muted)',
                    }}
                  >
                    {String(discovered ?? '—')}
                  </span>
                </label>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ marginTop: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>
        Only conflicting fields are shown. Non-conflicting fields are unchanged.
      </p>
    </div>
  );
}

const thStyle = {
  textAlign: 'left',
  padding: '6px 8px',
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  color: 'var(--color-text-muted)',
  borderBottom: '1px solid var(--color-border)',
};

const tdStyle = {
  padding: '8px 8px',
  verticalAlign: 'middle',
};

ConflictResolver.propTypes = {
  conflicts: PropTypes.arrayOf(
    PropTypes.shape({
      field: PropTypes.string.isRequired,
      stored: PropTypes.any,
      discovered: PropTypes.any,
    })
  ).isRequired,
  onChange: PropTypes.func.isRequired,
};
