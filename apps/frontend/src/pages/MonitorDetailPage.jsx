import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getMonitor,
  getMonitorEvents,
  getMonitorHistory,
  getMonitorUptime,
  pauseMonitor,
  resumeMonitor,
  runCheck,
} from '../api/monitor';
import { useMonitorStream } from '../hooks/useMonitorStream';
import { useToast } from '../components/common/Toast';
import CheckHistoryBar from '../components/monitors/CheckHistoryBar';
import LatencyChart from '../components/monitors/LatencyChart';
import StatusPill from '../components/monitors/StatusPill';

export default function MonitorDetailPage() {
  const { id } = useParams();
  const monitorId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();
  const [monitor, setMonitor] = useState(null);
  const [events, setEvents] = useState([]);
  const [history, setHistory] = useState([]);
  const [uptime, setUptime] = useState(null);
  const { statuses } = useMonitorStream({ monitorIds: [monitorId] });

  const refresh = useCallback(async () => {
    const [m, ev, hist, up] = await Promise.all([
      getMonitor(monitorId),
      getMonitorEvents(monitorId, 100),
      getMonitorHistory(monitorId, { hours: 24 }),
      getMonitorUptime(monitorId),
    ]);
    setMonitor(m.data);
    setEvents(ev.data);
    setHistory(hist.data);
    setUptime(up.data);
  }, [monitorId]);

  useEffect(() => {
    refresh().catch(() => navigate('/monitors'));
    const t = setInterval(() => refresh().catch(() => {}), 60000);
    return () => clearInterval(t);
  }, [refresh, navigate]);

  if (!monitor) return <div className="page">Loading…</div>;

  const status = statuses.get(monitorId)?.status || monitor.status;
  const tls = monitor.check_type === 'http' && monitor.config?.url?.startsWith('https');
  const lastPolled = uptime?.last_polled_at ?? monitor.last_polled_at;

  const handleCheck = () =>
    runCheck(monitorId)
      .then(() => {
        toast.success('Probe triggered.');
        return refresh();
      })
      .catch((err) => toast.error(err?.response?.data?.detail || 'Failed to run check'));

  const handleToggle = () =>
    (monitor.enabled ? pauseMonitor(monitorId) : resumeMonitor(monitorId))
      .then(refresh)
      .catch((err) => toast.error(err?.response?.data?.detail || 'Failed to update monitor'));

  return (
    <div className="page">
      <div className="page-header">
        <div className="tw-flex tw-items-center tw-gap-3">
          <button className="btn" onClick={() => navigate('/monitors')}>
            ← Back
          </button>
          <h2>{monitor.name}</h2>
          <StatusPill status={status} enabled={monitor.enabled} />
        </div>
        <div className="tw-flex tw-gap-2">
          <button className="btn" onClick={handleCheck}>
            Check now
          </button>
          <button className="btn" onClick={handleToggle}>
            {monitor.enabled ? 'Pause' : 'Resume'}
          </button>
        </div>
      </div>

      <dl className="tw-grid tw-grid-cols-2 tw-gap-x-6 tw-gap-y-1" style={{ maxWidth: 520 }}>
        <dt className="text-muted">Type</dt>
        <dd>{monitor.check_type.toUpperCase()}</dd>
        <dt className="text-muted">Target</dt>
        <dd>{monitor.config?.url || monitor.host}</dd>
        <dt className="text-muted">Interval</dt>
        <dd>{monitor.interval_secs}s</dd>
        <dt className="text-muted">Total Uptime</dt>
        <dd>{uptime?.pct_total != null ? `${uptime.pct_total}%` : '—'}</dd>
        <dt className="text-muted">Last Polled</dt>
        <dd>{lastPolled ? new Date(lastPolled).toLocaleString() : '—'}</dd>
        <dt className="text-muted">24 Hour</dt>
        <dd>{uptime?.pct_24h != null ? `${uptime.pct_24h}%` : '—'}</dd>
        <dt className="text-muted">7-Day</dt>
        <dd>{uptime?.pct_7d != null ? `${uptime.pct_7d}%` : '—'}</dd>
        <dt className="text-muted">30-Day</dt>
        <dd>{uptime?.pct_30d != null ? `${uptime.pct_30d}%` : '—'}</dd>
        <dt className="text-muted">365-Day</dt>
        <dd>{uptime?.pct_365d != null ? `${uptime.pct_365d}%` : '—'}</dd>
      </dl>

      <section style={{ marginTop: 20 }}>
        <h3>Recent checks</h3>
        <CheckHistoryBar events={events} max={80} />
      </section>

      <section style={{ marginTop: 20 }}>
        <h3>Latency (24h)</h3>
        <LatencyChart points={history} />
      </section>

      {tls && (
        <section style={{ marginTop: 20 }}>
          <h3>Certificate</h3>
          <p className="text-muted">
            Certificate details are captured on each check; days remaining is recorded in the
            latency history as <code>cert_days_remaining</code>.
          </p>
        </section>
      )}

      <section style={{ marginTop: 20 }}>
        <h3>Events</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Event</th>
              <th>Message</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => (
              <tr key={ev.id}>
                <td>{new Date(ev.created_at).toLocaleString()}</td>
                <td>{ev.status_from ? `${ev.status_from} → ${ev.status_to}` : ev.status_to}</td>
                <td>{ev.msg}</td>
                <td>{ev.duration_secs != null ? `${Math.round(ev.duration_secs)}s` : '—'}</td>
              </tr>
            ))}
            {events.length === 0 && (
              <tr>
                <td colSpan={4} className="text-muted">
                  No events yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
