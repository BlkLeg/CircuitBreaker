import React from 'react';
import { FILTER_NODE_TYPES, NODE_STYLES, NODE_TYPE_LABELS } from './mapConstants';

const HW_ROLE_CHIPS = [
  { value: 'ups', label: 'UPS' },
  { value: 'pdu', label: 'PDU' },
  { value: 'access_point', label: 'AP' },
  { value: 'sbc', label: 'SBC' },
];

/**
 * Toolbar row: node-type toggle buttons + Docker toggle + hardware sub-role chips.
 * All filter state is owned by the parent; this component is presentation-only.
 */
export default function NodeTypeFilterBar({
  includeTypes,
  setIncludeTypes,
  hwRoleFilter,
  setHwRoleFilter,
}) {
  return (
    <>
      {/* Node type toggles */}
      <span
        style={{
          color: 'var(--color-text-muted)',
          fontSize: 11,
          borderLeft: '1px solid var(--color-border)',
          paddingLeft: 8,
        }}
      >
        Show:
      </span>

      {FILTER_NODE_TYPES.map((type) => {
        const style = NODE_STYLES[type];
        return (
          <button
            key={type}
            onClick={() => setIncludeTypes((prev) => ({ ...prev, [type]: !prev[type] }))}
            style={{
              padding: '3px 8px',
              borderRadius: 4,
              border: `1px solid ${style.borderColor}`,
              background: includeTypes[type] ? style.background : 'transparent',
              color: includeTypes[type] ? '#fff' : style.background,
              fontSize: 11,
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            {NODE_TYPE_LABELS[type]}
          </button>
        );
      })}

      {/* Docker toggle — single button controlling both docker_network + docker_container */}
      <button
        onClick={() => setIncludeTypes((prev) => ({ ...prev, docker: !prev.docker }))}
        style={{
          padding: '3px 8px',
          borderRadius: 4,
          border: '1px solid #1cb8d8',
          background: includeTypes.docker ? '#0b6e8e' : 'transparent',
          color: includeTypes.docker ? '#fff' : '#1cb8d8',
          fontSize: 11,
          cursor: 'pointer',
          transition: 'all 0.15s',
        }}
      >
        Docker
      </button>

      {/* Hardware sub-role chips */}
      {includeTypes.hardware && (
        <>
          <span
            style={{
              color: 'var(--color-text-muted)',
              fontSize: 11,
              borderLeft: '1px solid var(--color-border)',
              paddingLeft: 8,
            }}
          >
            Role:
          </span>
          {HW_ROLE_CHIPS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setHwRoleFilter((prev) => (prev === value ? null : value))}
              style={{
                padding: '3px 8px',
                borderRadius: 4,
                fontSize: 11,
                cursor: 'pointer',
                border: '1px solid #4a7fa5',
                background: hwRoleFilter === value ? '#4a7fa5' : 'transparent',
                color: hwRoleFilter === value ? '#fff' : '#4a7fa5',
                transition: 'all 0.15s',
              }}
            >
              {label}
            </button>
          ))}
        </>
      )}
    </>
  );
}
