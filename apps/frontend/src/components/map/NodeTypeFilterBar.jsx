import React from 'react';
import { FILTER_NODE_TYPES, NODE_STYLES, NODE_TYPE_LABELS } from './mapConstants';
import { useHardwareRoles } from '../../hooks/useHardwareRoles';

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
  const { roles } = useHardwareRoles();
  const HW_ROLE_CHIPS = roles
    .filter((r) => (r.rank ?? 5) <= 4)
    .map((r) => ({ value: r.slug, label: r.label }));

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
        const style = NODE_STYLES.get(type);
        const isActive = includeTypes.get(type);
        return (
          <button
            key={type}
            onClick={() =>
              setIncludeTypes((prev) => {
                const next = new Map(prev);
                next.set(type, !prev.get(type));
                return next;
              })
            }
            style={{
              padding: '3px 8px',
              borderRadius: 4,
              border: `1px solid ${style?.borderColor}`,
              background: isActive ? style?.background : 'transparent',
              color: isActive ? '#fff' : style?.background,
              fontSize: 11,
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            {NODE_TYPE_LABELS.get(type)}
          </button>
        );
      })}

      {/* Docker toggle — single button controlling both docker_network + docker_container */}
      <button
        onClick={() =>
          setIncludeTypes((prev) => {
            const next = new Map(prev);
            next.set('docker', !prev.get('docker'));
            return next;
          })
        }
        style={{
          padding: '3px 8px',
          borderRadius: 4,
          border: '1px solid #0b6e8e',
          background: includeTypes.get('docker') ? '#0b6e8e' : 'transparent',
          color: includeTypes.get('docker') ? '#fff' : '#0b6e8e',
          fontSize: 11,
          cursor: 'pointer',
          transition: 'all 0.15s',
        }}
      >
        🐳 Docker
      </button>

      {/* Hardware sub-role chips */}
      {includeTypes.get('hardware') && (
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
