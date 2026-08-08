import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import CheckHistoryBar from './CheckHistoryBar';
import LatencyChart from './LatencyChart';
import { formatSince } from './monitorFormat';

/**
 * MonitorCardDetail — the body a monitor card reveals when expanded: 24h
 * latency, headline stats, the full check history, the latest events and the
 * actions. The full-page view stays available for deep links.
 */
export default function MonitorCardDetail({
  monitor,
  history,
  events,
  loading,
  busy,
  onCheckNow,
  onPause,
  onEdit,
  onDelete,
}) {
  const target = monitor.config?.url || monitor.host;
  return (
    <div className="mon-card-detail">
      <p className="mon-target">
        {target} · every {monitor.interval_secs}s
        {monitor.target_type ? ` · ${monitor.target_type.replace('_', ' ')}` : ''}
      </p>

      {loading ? (
        <p className="text-muted">Loading check history…</p>
      ) : (
        <>
          <LatencyChart points={history} height={140} />

          <div className="mon-stats">
            <div>
              <b>{monitor.uptime_pct_24h != null ? `${monitor.uptime_pct_24h}%` : '—'}</b>
              <span>Uptime 24h</span>
            </div>
            <div>
              <b>{monitor.latency_ms != null ? `${Math.round(monitor.latency_ms)} ms` : '—'}</b>
              <span>Latency</span>
            </div>
            <div>
              <b>
                {monitor.retries} / {monitor.max_retries}
              </b>
              <span>Retries used</span>
            </div>
            <div>
              <b>{formatSince(monitor.last_status_change_at)}</b>
              <span>In state</span>
            </div>
            <div>
              {/* §7's "last successful result time". A server-executed monitor
                  has no probe run, so it falls back to its last poll. */}
              <b>{formatSince(monitor.probe_last_result_at || monitor.last_polled_at)}</b>
              <span>Last result</span>
            </div>
          </div>

          <CheckHistoryBar events={events} size="md" />

          {events.length > 0 && (
            <ul className="mon-events">
              {events.slice(0, 5).map((ev) => (
                <li key={ev.id}>
                  <time dateTime={ev.created_at}>
                    {new Date(ev.created_at).toLocaleTimeString()}
                  </time>
                  <span>
                    {ev.status_to} — {ev.msg}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <div className="mon-actions">
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onCheckNow}>
          Check now
        </button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onPause}>
          {monitor.enabled ? 'Pause' : 'Resume'}
        </button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onEdit}>
          Edit
        </button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onDelete}>
          Delete
        </button>
        {monitor.probe_agent_id != null && (
          <Link className="btn btn-sm" to={`/agents/${monitor.probe_agent_id}`}>
            {monitor.probe_agent?.name ? `Agent: ${monitor.probe_agent.name}` : 'View agent'} →
          </Link>
        )}
        <Link className="btn btn-sm" to={`/monitors/${monitor.id}`}>
          Open full page →
        </Link>
      </div>
    </div>
  );
}

MonitorCardDetail.propTypes = {
  monitor: PropTypes.object.isRequired,
  history: PropTypes.arrayOf(PropTypes.object).isRequired,
  events: PropTypes.arrayOf(PropTypes.object).isRequired,
  loading: PropTypes.bool,
  busy: PropTypes.bool,
  onCheckNow: PropTypes.func.isRequired,
  onPause: PropTypes.func.isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
