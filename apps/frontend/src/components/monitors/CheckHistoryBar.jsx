import React from 'react';

const COLORS = {
  up: 'var(--color-success, #22c55e)',
  down: 'var(--color-danger, #ef4444)',
  pending: 'var(--color-warning, #eab308)',
  maintenance: 'var(--color-info, #3b82f6)',
  paused: 'var(--color-muted, #9ca3af)',
  resumed: 'var(--color-muted, #9ca3af)',
};

/** events: MonitorEventRead[] newest-first (as the API returns them). */
export default function CheckHistoryBar({ events = [], max = 40 }) {
  const segments = [...events].slice(0, max).reverse();
  if (segments.length === 0) {
    return <span className="text-muted">no history</span>;
  }
  return (
    <div style={{ display: 'flex', gap: 2, alignItems: 'center' }} aria-label="check history">
      {segments.map((ev) => (
        <span
          key={ev.id}
          title={`${ev.status_to} — ${ev.msg || ev.event_type} (${new Date(ev.created_at).toLocaleString()})`}
          style={{
            width: 6,
            height: 18,
            borderRadius: 2,
            background: COLORS[ev.status_to] || COLORS.paused,
          }}
        />
      ))}
    </div>
  );
}
