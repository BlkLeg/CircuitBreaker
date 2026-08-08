import React from 'react';
import PropTypes from 'prop-types';
import CheckHistoryBar from './CheckHistoryBar';
import LatencySparkline from './LatencySparkline';
import MonitorCardDetail from './MonitorCardDetail';

/** Which group a monitor belongs to — a disabled monitor is paused, whatever it last reported. */
export function groupStatusOf(monitor) {
  return monitor.enabled ? monitor.status || 'pending' : 'paused';
}

/**
 * Slice 3 §7: which vantage runs the check. Deliberately *not* folded into
 * groupStatusOf/headlineOf above — MonitorsPage imports groupStatusOf for the
 * summary counts, the group buckets and the status filter, so execution state
 * leaking into it would silently rewrite the dashboard (D-13).
 */
export function probeVantageLabel(monitor) {
  if (monitor.probe_agent_id == null) return 'via Server';
  return `via ${monitor.probe_agent?.name || `agent ${monitor.probe_agent_id}`}`;
}

/**
 * The secondary execution condition, or null when the vantage is healthy or is
 * the server. A Map so a wire value can never index into Object.prototype.
 */
const EXEC_LABELS = new Map([
  ['queued', 'probe queued'],
  ['running', 'probe running'],
  ['stale', 'probe stale'],
  ['unavailable', 'probe unavailable'],
]);

export function executionConditionOf(monitor) {
  if (monitor.probe_agent_id == null) return null;
  return EXEC_LABELS.get(monitor.probe_execution_status) || null;
}

/** The card footer's headline figure. */
export function headlineOf(monitor) {
  if (!monitor.enabled) return 'Paused';
  switch (monitor.status) {
    case 'up':
      return monitor.latency_ms != null ? `${Math.round(monitor.latency_ms)} ms` : 'Up';
    case 'down':
      return 'Down';
    case 'maintenance':
      return 'Maintenance';
    case 'pending':
      return monitor.max_retries > 0
        ? `Retry ${monitor.retries}/${monitor.max_retries}`
        : 'Pending';
    default:
      return monitor.status || 'Pending';
  }
}

/**
 * MonitorCard — one monitor on the wall. The face is a button that expands the
 * card in place; the expanded body's own buttons sit outside that button so they
 * never toggle the card.
 */
export default function MonitorCard({
  monitor,
  expanded,
  onToggle,
  detail,
  busy,
  onCheckNow,
  onPause,
  onEdit,
  onDelete,
}) {
  const status = groupStatusOf(monitor);
  const target = monitor.config?.url || monitor.host;
  const showSparkline = status === 'up' && (monitor.latency_series?.length ?? 0) > 0;
  const execCondition = executionConditionOf(monitor);

  return (
    <article className="mon-card" data-status={status} data-expanded={expanded || undefined}>
      <button
        type="button"
        className="mon-card-face"
        aria-expanded={expanded}
        onClick={() => onToggle(monitor.id)}
      >
        <span className="mon-card-head">
          <span className="mon-card-name">{monitor.name}</span>
          <span className="mon-badge">{monitor.check_type.toUpperCase()}</span>
        </span>
        <span className="mon-target" style={{ display: 'block' }}>
          <span className="mon-target-addr">
            {monitor.target_type ? `${target} · ${monitor.target_type.replace('_', ' ')}` : target}
          </span>
          <span className="mon-vantage"> · {probeVantageLabel(monitor)}</span>
        </span>
        {execCondition && (
          <span
            className="mon-exec"
            data-exec={monitor.probe_execution_status}
            title={monitor.probe_execution_reason || undefined}
            style={{ display: 'block' }}
          >
            {execCondition}
          </span>
        )}
        <span className="mon-card-mid" style={{ display: 'block' }}>
          {showSparkline ? (
            <LatencySparkline series={monitor.latency_series} />
          ) : (
            <CheckHistoryBar events={monitor.recent_checks || []} max={20} />
          )}
        </span>
        <span className="mon-card-foot">
          <span className="mon-headline">{headlineOf(monitor)}</span>
          <span className="mon-uptime">
            {monitor.uptime_pct_24h != null ? `${monitor.uptime_pct_24h}% · 24h` : '—'}
          </span>
        </span>
      </button>

      {expanded && (
        <MonitorCardDetail
          monitor={monitor}
          history={detail?.history || []}
          events={detail?.events || monitor.recent_checks || []}
          loading={detail?.loading ?? true}
          busy={busy}
          onCheckNow={onCheckNow}
          onPause={onPause}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      )}
    </article>
  );
}

MonitorCard.propTypes = {
  monitor: PropTypes.object.isRequired,
  expanded: PropTypes.bool,
  onToggle: PropTypes.func.isRequired,
  detail: PropTypes.object,
  busy: PropTypes.bool,
  onCheckNow: PropTypes.func.isRequired,
  onPause: PropTypes.func.isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
