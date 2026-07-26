import React, { useState } from 'react';
import StatusPill from './StatusPill';

/**
 * MonitorCell — row action cluster for the inventory tables.
 *
 * No monitor yet  → "Monitor" (enables one).
 * Monitor running → status pill + Pause + Check now.
 * Monitor paused  → status pill + Resume.
 */
export default function MonitorCell({ state, onEnable, onPause, onResume, onCheckNow }) {
  const [busy, setBusy] = useState(false);

  const run = async (fn) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <button
        className="btn btn-sm"
        title="Start monitoring this entity"
        disabled={busy}
        onClick={() => run(onEnable)}
      >
        Monitor
      </button>
    );
  }

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      {state.enabled ? (
        <>
          <button
            className="btn btn-sm"
            title="Pause monitoring"
            disabled={busy}
            onClick={() => run(onPause)}
          >
            Pause
          </button>
          <button
            className="btn btn-sm"
            title="Run a check now"
            disabled={busy}
            onClick={() => run(onCheckNow)}
          >
            Check
          </button>
        </>
      ) : (
        <button
          className="btn btn-sm"
          title="Resume monitoring"
          disabled={busy}
          onClick={() => run(onResume)}
        >
          Resume
        </button>
      )}
    </span>
  );
}

/**
 * MonitorStatusCell — the read-only status column that pairs with MonitorCell.
 */
export function MonitorStatusCell({ state }) {
  if (!state) return <span className="text-muted">—</span>;
  const bits = [];
  if (state.uptime_pct_24h != null) bits.push(`${state.uptime_pct_24h}% uptime (24h)`);
  if (state.latency_ms != null) bits.push(`${Math.round(state.latency_ms)} ms`);
  return (
    <StatusPill
      status={state.status}
      enabled={state.enabled}
      title={bits.join(' · ') || undefined}
    />
  );
}
