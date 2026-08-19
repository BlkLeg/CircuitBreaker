import React from 'react';
import { CHIP_STYLES, FILTER_NODE_TYPES, NODE_TYPE_LABELS } from './mapConstants';
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
        // ACC-10: CHIP_STYLES, not NODE_STYLES — the node palette is tuned for
        // 40px nodes and fails 4.5:1 as 11px chip text in both states.
        const chip = CHIP_STYLES.get(type);
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
            aria-pressed={!!isActive}
            style={{
              padding: '3px 8px',
              borderRadius: 4,
              border: `1px solid ${chip?.chipBg}`,
              background: isActive ? chip?.chipBg : 'transparent',
              color: isActive ? '#fff' : chip?.chipText,
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
        aria-pressed={!!includeTypes.get('docker')}
        style={{
          padding: '3px 8px',
          borderRadius: 4,
          border: `1px solid ${CHIP_STYLES.get('docker_network').chipBg}`,
          background: includeTypes.get('docker')
            ? CHIP_STYLES.get('docker_network').chipBg
            : 'transparent',
          color: includeTypes.get('docker') ? '#fff' : CHIP_STYLES.get('docker_network').chipText,
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
                border: `1px solid ${CHIP_STYLES.get('hardware').chipBg}`,
                background:
                  hwRoleFilter === value ? CHIP_STYLES.get('hardware').chipBg : 'transparent',
                color: hwRoleFilter === value ? '#fff' : CHIP_STYLES.get('hardware').chipText,
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
