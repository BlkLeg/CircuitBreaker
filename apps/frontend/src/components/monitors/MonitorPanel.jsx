import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import {
  createTargetMonitor,
  getMonitorEvents,
  getTargetSummary,
  pauseTargetMonitor,
  resumeTargetMonitor,
  runTargetCheck,
} from '../../api/monitor';
import { useToast } from '../common/Toast';
import CheckHistoryBar from './CheckHistoryBar';
import StatusPill from './StatusPill';

/**
 * MonitorPanel — reachability monitoring for one inventory entity, shown in the
 * hardware / compute / service / external-node detail drawers. Mirrors
 * TelemetryPanel's collapsible shell; the numbers come from the same engine as
 * /monitors.
 */
export default function MonitorPanel({ targetType, targetId }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!targetId) return;
    try {
      const { data } = await getTargetSummary(targetType, [targetId]);
      const row = data.find((r) => r.target_id === targetId) || null;
      setState(row);
      if (row) {
        const ev = await getMonitorEvents(row.monitor_id, 40);
        setEvents(ev.data);
      } else {
        setEvents([]);
      }
    } catch {
      // Non-fatal: the panel just shows its empty state.
      setState(null);
    } finally {
      setLoading(false);
    }
  }, [targetType, targetId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const run = async (fn, successMsg) => {
    setBusy(true);
    try {
      await fn();
      if (successMsg) toast.success(successMsg);
      await refresh();
    } catch (err) {
      const status = err?.response?.status;
      toast.error(
        status === 404
          ? 'No address to probe — add an IP address, hostname, or URL first.'
          : err?.response?.data?.detail || 'Failed to update monitoring.'
      );
    } finally {
      setBusy(false);
    }
  };

  if (!targetId) return null;

  return (
    <details
      open={open}
      onToggle={(e) => setOpen(e.target.open)}
      style={{
        marginTop: 24,
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        padding: '10px 14px',
      }}
    >
      <summary
        style={{
          cursor: 'pointer',
          fontWeight: 600,
          fontSize: 13,
          color: 'var(--color-text)',
          listStyle: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        Monitoring
        {state && <StatusPill status={state.status} enabled={state.enabled} />}
      </summary>

      <div style={{ marginTop: 12 }}>
        {loading && <p className="text-muted">Loading…</p>}

        {!loading && !state && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <p className="text-muted" style={{ margin: 0, fontSize: 13 }}>
              Not monitored yet.
            </p>
            <button
              className="btn btn-sm btn-primary"
              disabled={busy}
              onClick={() =>
                run(() => createTargetMonitor(targetType, targetId), 'Monitoring enabled.')
              }
            >
              Enable monitoring
            </button>
          </div>
        )}

        {!loading && state && (
          <>
            <div
              style={{
                display: 'flex',
                gap: 24,
                flexWrap: 'wrap',
                fontSize: 13,
                marginBottom: 12,
              }}
            >
              <div>
                <div className="text-muted" style={{ fontSize: 11 }}>
                  Uptime 24h
                </div>
                {state.uptime_pct_24h != null ? `${state.uptime_pct_24h}%` : '—'}
              </div>
              <div>
                <div className="text-muted" style={{ fontSize: 11 }}>
                  Latency
                </div>
                {state.latency_ms != null ? `${Math.round(state.latency_ms)} ms` : '—'}
              </div>
              <div>
                <div className="text-muted" style={{ fontSize: 11 }}>
                  Checks
                </div>
                {state.monitor_ids.length}
              </div>
            </div>

            <CheckHistoryBar events={events} />

            <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              {state.enabled ? (
                <button
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() =>
                    run(() => pauseTargetMonitor(targetType, targetId), 'Monitoring paused.')
                  }
                >
                  Pause
                </button>
              ) : (
                <button
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() =>
                    run(() => resumeTargetMonitor(targetType, targetId), 'Monitoring resumed.')
                  }
                >
                  Resume
                </button>
              )}
              <button
                className="btn btn-sm"
                disabled={busy}
                onClick={() => run(() => runTargetCheck(targetType, targetId), 'Probe triggered.')}
              >
                Check now
              </button>
              <Link className="btn btn-sm" to={`/monitors/${state.monitor_id}`}>
                Open monitor →
              </Link>
            </div>
          </>
        )}
      </div>
    </details>
  );
}

MonitorPanel.propTypes = {
  targetType: PropTypes.oneOf(['hardware', 'compute_unit', 'service', 'external_node']).isRequired,
  targetId: PropTypes.number,
};
