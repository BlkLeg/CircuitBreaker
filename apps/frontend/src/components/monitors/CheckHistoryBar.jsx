/* eslint-disable security/detect-object-injection -- internal status keys */
import React from 'react';

const COLORS = {
  up: 'var(--color-success)',
  down: 'var(--color-danger)',
  pending: 'var(--color-warning)',
  maintenance: 'var(--color-info)',
  paused: 'var(--color-muted)',
  resumed: 'var(--color-muted)',
};

// sm sits on a dashboard card face, md inside an expanded card or the detail page.
const SIZES = { sm: { width: 4, height: 15, gap: 1.5 }, md: { width: 6, height: 18, gap: 2 } };

/** events: MonitorEventRead[] newest-first (as the API returns them). */
export default function CheckHistoryBar({ events = [], max = 40, size = 'sm' }) {
  const segments = [...events].slice(0, max).reverse();
  const dim = SIZES[size] || SIZES.sm;
  if (segments.length === 0) {
    return <span className="text-muted">no history</span>;
  }
  return (
    <div style={{ display: 'flex', gap: dim.gap, alignItems: 'center' }} aria-label="check history">
      {segments.map((ev) => (
        <span
          key={ev.id}
          title={`${ev.status_to} — ${ev.msg || ev.event_type} (${new Date(ev.created_at).toLocaleString()})`}
          style={{
            width: dim.width,
            height: dim.height,
            borderRadius: 2,
            background: COLORS[ev.status_to] || COLORS.paused,
          }}
        />
      ))}
    </div>
  );
}
