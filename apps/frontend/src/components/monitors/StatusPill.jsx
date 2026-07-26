/* eslint-disable security/detect-object-injection -- internal status keys */
import React from 'react';

/**
 * StatusPill — the single monitor status badge used by the monitors dashboard
 * and by the hardware / compute / services inventory pages.
 */

export const STATUS_LABEL = {
  up: 'Up',
  down: 'Down',
  pending: 'Pending',
  maintenance: 'Maintenance',
};

export const STATUS_COLORS = {
  up: 'var(--color-success)',
  down: 'var(--color-danger)',
  pending: 'var(--color-warning)',
  maintenance: 'var(--color-info)',
  paused: 'var(--color-muted)',
};

export default function StatusPill({ status, enabled = true, title }) {
  const key = enabled ? status : 'paused';
  const label = enabled ? STATUS_LABEL[status] || status : 'Paused';
  return (
    <span
      title={title}
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        color: '#fff',
        background: STATUS_COLORS[key] || STATUS_COLORS.paused,
      }}
    >
      {label}
    </span>
  );
}
